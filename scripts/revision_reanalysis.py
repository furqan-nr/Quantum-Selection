"""Post-hoc re-analysis added in the TOSEM revision (NOT pre-registered; frozen files are read-only).

Reads data_scaleup/ (19 mutation events) and writes results/revision_reanalysis.json:
  - per-event AUC / seconds-to-first-detection for every selector (+ random event-mean over seeds)
  - paired Wilcoxon signed-rank (two-sided) with Holm correction, matched-pairs rank-biserial effect
  - original-9 vs new-10 operator cohorts
  - fraction of tests that detect each fault
  - drop_vf2_post_layout sensitivity (counting non-pass, unattributed labels as detections)
Run from repo root:  PYTHONPATH=src python scripts/revision_reanalysis.py
"""
from __future__ import annotations
import json, random, statistics
from pathlib import Path
import numpy as np
from scipy.stats import wilcoxon
from cart.metrics.evaluate import _build_payloads, _run_metrics
from cart.metrics.curves import event_metrics
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP

ROOT = Path(__file__).resolve().parents[1]
ORIG9 = {"mut2-disable-optimization-loop-01", "mut2-drop-vf2-post-layout-01", "mut2-downgrade-routing-01",
         "mut2-insert-redundant-cx-pair-01", "mut2-drop-optimization-stage-01", "mut2-force-opt-level-1-01",
         "mut2-force-opt-level-0-01", "mut2-downgrade-layout-trivial-01", "mut2-insert-redundant-x-pair-01"}
SEEDS = list(range(20))
DET = ["cheapest_first", "diversity_only", "history_only", "change_stage", "proposed", "decomposed"]


def r4(x):
    """AUCs are compared at the 4-decimal precision at which evaluate() reports them, so that
    sub-1e-4 differences (which are not practically meaningful) count as ties."""
    return round(float(x), 4)


def paired_boot_ci(a, b, n=5000, seed=0):
    """Percentile bootstrap 95% CI of the mean paired difference, resampling events."""
    d = np.array([r4(x) - r4(y) for x, y in zip(a, b)]); rng = np.random.default_rng(seed)
    m = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def rbc(a, b):
    """Matched-pairs rank-biserial correlation (positive: a > b)."""
    d = np.array([r4(x) - r4(y) for x, y in zip(a, b)]); d = d[np.abs(d) > 1e-9]
    if len(d) == 0: return 0.0
    r = np.argsort(np.argsort(np.abs(d))) + 1.0
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); out = [None] * len(ps); run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i])); out[i] = run
    return out


def main():
    pay = _build_payloads(ROOT / "data_scaleup", None, "all")
    pay = {p["event_id"]: p for p in pay}
    ids = sorted(pay)
    per = {}
    for eid in ids:
        p = pay[eid]; row = {}
        for name in DET:
            em, _ = _run_metrics(SELECTORS_SCALEUP[name], p["ctx"], eid, p["cost"], p["detects"])
            row[name] = dict(auc=em.auc_detection_vs_budget, detected=em.detected, sec=em.ttfr_cost if em.detected else None,
                             full=em.full_suite_cost)
        aucs, secs = [], []
        for s in SEEDS:
            em, _ = _run_metrics(SELECTORS_SCALEUP["random"], p["ctx"], eid, p["cost"], p["detects"], seed=s)
            aucs.append(em.auc_detection_vs_budget); secs.append(em.ttfr_cost if em.detected else None)
        row["random"] = dict(auc=float(np.mean(aucs)), detected=any(x is not None for x in secs),
                             sec=float(np.mean([x for x in secs if x is not None])) if any(x is not None for x in secs) else None,
                             full=row["proposed"]["full"])
        per[eid] = row
    res = {"n_events": len(ids), "per_event": per}
    cohorts = {"all19": ids, "orig9": [i for i in ids if i in ORIG9], "new10": [i for i in ids if i not in ORIG9]}
    res["means"] = {c: {n: float(np.mean([per[i][n]["auc"] for i in L])) for n in DET + ["random"]} for c, L in cohorts.items()}
    det_ids = [i for i in ids if any(pay[i]["detects"].values())]
    res["means_detectable_only"] = {"n_events": len(det_ids), **{n: float(np.mean([per[i][n]["auc"] for i in det_ids])) for n in DET + ["random"]}}
    res["detected_counts"] = {c: {n: int(sum(per[i][n]["detected"] for i in L)) for n in DET + ["random"]} for c, L in cohorts.items()}
    res["mean_seconds_to_first_detection"] = {c: {n: (float(np.mean([per[i][n]["sec"] for i in L if per[i][n]["sec"] is not None])) if any(per[i][n]["sec"] is not None for i in L) else None) for n in DET + ["random"]} for c, L in cohorts.items()}
    res["median_pct_of_full_suite_cost"] = {c: {n: float(np.median([100 * per[i][n]["sec"] / per[i][n]["full"] for i in L if per[i][n]["sec"] is not None])) for n in DET + ["random"]} for c, L in cohorts.items()}
    tests = {}
    for c, L in cohorts.items():
        out = {}
        for ref in ["proposed", "decomposed"]:
            rows = []
            for other in [n for n in DET + ["random"] if n != ref]:
                a = [per[i][ref]["auc"] for i in L]; b = [per[i][other]["auc"] for i in L]
                if all(r4(x) == r4(y) for x, y in zip(a, b)): p = 1.0
                else:
                    try: p = float(wilcoxon([r4(x) for x in a], [r4(y) for y in b], zero_method="wilcox", method="auto").pvalue)
                    except ValueError: p = 1.0
                rows.append(dict(vs=other, mean_diff=float(np.mean(np.array(a) - np.array(b))), diff_ci95=paired_boot_ci(a, b), rank_biserial=rbc(a, b),
                                 wins=int(sum(r4(x) > r4(y) for x, y in zip(a, b))), losses=int(sum(r4(x) < r4(y) for x, y in zip(a, b))),
                                 ties=int(sum(r4(x) == r4(y) for x, y in zip(a, b))), p=p))
            for r, ph in zip(rows, holm([r["p"] for r in rows])): r["p_holm"] = ph
            out[ref] = rows
        # One Holm family of the 7 distinct substantive comparisons (history_only and change_stage are
        # identical to cheapest_first on this corpus, and proposed-vs-decomposed is one test, not two).
        fam = [("proposed", "cheapest_first"), ("proposed", "diversity_only"), ("proposed", "decomposed"), ("proposed", "random"),
               ("decomposed", "cheapest_first"), ("decomposed", "diversity_only"), ("decomposed", "random")]
        look = {(ref, r["vs"]): r for ref in out for r in out[ref]}
        hp = holm([look[k]["p"] for k in fam])
        fam_p = {k: h for k, h in zip(fam, hp)}
        for ref in out:
            for r in out[ref]:
                key = (ref, "cheapest_first" if r["vs"] in ("history_only", "change_stage") else r["vs"])
                if key == ("decomposed", "proposed"): key = ("proposed", "decomposed")
                r["p_holm_family7"] = fam_p.get(key)
        tests[c] = out
    res["paired_tests"] = tests
    # event-level bootstrap CI for random ordering (each event's AUC is first averaged over the 20 seeds)
    rng = np.random.default_rng(0)
    res["random_event_bootstrap_ci"] = {}
    for c, L in cohorts.items():
        v = np.array([per[i]["random"]["auc"] for i in L])
        bm = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(5000)]
        res["random_event_bootstrap_ci"][c] = dict(mean=float(v.mean()), ci95=[float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))])
    # detection fractions
    frac = {}
    for eid in ids:
        d = pay[eid]["detects"]; frac[eid] = dict(detecting=int(sum(d.values())), total=len(d), fraction=sum(d.values()) / len(d))
    res["detection_fraction"] = frac
    # vf2 sensitivity: count any non-pass label as detection for the vf2 event
    labs = json.load(open(ROOT / "data_scaleup/derived/labels.json"))["labels"]
    vf = "mut2-drop-vf2-post-layout-01"
    rows = [r for r in labs if r["event_id"] == vf]
    alt = {r["test_id"]: r["label"] in ("functional_fail", "semantic_fail") for r in rows}
    cost = pay[vf]["cost"]; sens = {}
    for name in DET:
        rk = [t for t in SELECTORS_SCALEUP[name](pay[vf]["ctx"], vf, float("inf"), seed=0) if t in cost]
        em = event_metrics(rk, cost, alt); sens[name] = dict(auc=em.auc_detection_vs_budget, detected=em.detected)
    res["vf2_sensitivity"] = dict(n_functional_or_semantic_fail=int(sum(alt.values())),
                                  label_counts={k: sum(1 for r in rows if r["label"] == k) for k in set(r["label"] for r in rows)},
                                  per_selector=sens, original=per[vf])
    out = ROOT / "results" / "revision_reanalysis.json"
    out.write_text(json.dumps(res, indent=1, default=float)); print("wrote", out)

if __name__ == "__main__":
    main()
