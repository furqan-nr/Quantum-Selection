"""Additional post-hoc statistics for the TOSEM revision (NOT pre-registered; exploratory, added in
response to review). Frozen result files are only read, never written.

Writes results/revision_stats_extra.json with:
  A. Random ordering with 100 seeds (0..99) on both cohorts (data/, data_scaleup/): mean AUC, seed-based
     95% interval, event-level bootstrap 95% CI, detection at 20% budget; the two scale-up paired tests
     involving random (proposed vs random, decomposed vs random) recomputed with 100 seeds, Holm-adjusted
     within the same 7-comparison family as scripts/revision_reanalysis.py (the other 5 raw p-values are
     read from results/revision_reanalysis.json), shown side by side with the 20-seed values.
  B. Equivalence of decomposed vs diversity_only (19 events and the 17 events with >= 1 detecting unit):
     90% bootstrap CI vs margins, paired-t TOST, Bayesian bootstrap posterior.
  C. Practical significance (Bayesian bootstrap) for proposed vs diversity_only and proposed vs decomposed.
  D. Resampling power analysis of the Wilcoxon signed-rank test at a Bonferroni alpha of 0.05/7.
  E. Cost-cognizant APFD (APFDc, single fault) for all selectors on both cohorts, its Spearman
     correlation with AUC, and whether the selector ranking agrees with the AUC ranking.

Conventions follow scripts/revision_reanalysis.py: AUCs are compared after rounding to 4 decimals (r4),
Wilcoxon is two-sided with zero_method="wilcox", method="auto"; random is scored per event as the mean
over seeds of the per-seed AUC.

Run from repo root:  PYTHONPATH=src python scripts/revision_stats_extra.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from scipy.stats import wilcoxon, spearmanr, rankdata, t as tdist
from cart.metrics.evaluate import _build_payloads, _run_metrics
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "revision_stats_extra.json"
REANALYSIS = ROOT / "results" / "revision_reanalysis.json"
DET = ["cheapest_first", "diversity_only", "history_only", "change_stage", "proposed", "decomposed"]
ALL = DET + ["random"]
SEEDS100 = list(range(100))
SEEDS20 = list(range(20))
COHORTS = {"primary": "data", "scaleup": "data_scaleup"}
FAMILY7 = [("proposed", "cheapest_first"), ("proposed", "diversity_only"), ("proposed", "decomposed"),
           ("proposed", "random"), ("decomposed", "cheapest_first"), ("decomposed", "diversity_only"),
           ("decomposed", "random")]
MARGINS = [0.01, 0.02, 0.05]
ALPHA_BONF = 0.05 / 7
POWER_N = [19, 30, 40, 50, 60, 80, 100]


def r4(x):
    return round(float(x), 4)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); out = [None] * len(ps); run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i])); out[i] = run
    return out


def rbc(a, b):
    """Matched-pairs rank-biserial correlation (positive: a > b), as in revision_reanalysis.py."""
    d = np.array([r4(x) - r4(y) for x, y in zip(a, b)]); d = d[np.abs(d) > 1e-9]
    if len(d) == 0: return 0.0
    r = np.argsort(np.argsort(np.abs(d))) + 1.0
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def wilcox_p(a, b):
    """Two-sided Wilcoxon p exactly as revision_reanalysis.py computes it."""
    if all(r4(x) == r4(y) for x, y in zip(a, b)): return 1.0
    try: return float(wilcoxon([r4(x) for x in a], [r4(y) for y in b], zero_method="wilcox", method="auto").pvalue)
    except ValueError: return 1.0


def wilcox_p_diff(d):
    """Two-sided Wilcoxon p on already-rounded differences (used for power resampling)."""
    if np.all(np.abs(d) < 1e-12): return 1.0
    try: return float(wilcoxon(d, zero_method="wilcox", method="auto").pvalue)
    except ValueError: return 1.0


def apfdc(ranking, cost, detects):
    """Cost-cognizant APFD for a single fault: 1 - (C_before + 0.5*c_first)/C_total (0 if never detected)."""
    total = sum(cost[t] for t in ranking)
    before = 0.0
    for t in ranking:
        if detects.get(t, False):
            return 1.0 - (before + 0.5 * cost[t]) / total if total > 0 else 0.0
        before += cost[t]
    return 0.0


def score_cohort(data_dir):
    """Per-event AUC / det@20% / APFDc for every deterministic selector, and per-seed values for random."""
    pay = {p["event_id"]: p for p in _build_payloads(ROOT / data_dir, None, "all")}
    ids = sorted(pay)
    per, rnd = {}, {}
    for eid in ids:
        p = pay[eid]; row = {}
        for name in DET:
            sel = SELECTORS_SCALEUP[name]
            em, _ = _run_metrics(sel, p["ctx"], eid, p["cost"], p["detects"])
            rk = [t for t in sel(p["ctx"], eid, float("inf"), seed=0) if t in p["cost"]]
            row[name] = dict(auc=em.auc_detection_vs_budget, det20=em.detection_at_fraction[0.2],
                             apfdc=apfdc(rk, p["cost"], p["detects"]))
        seeds = []
        for s in SEEDS100:
            sel = SELECTORS_SCALEUP["random"]
            em, _ = _run_metrics(sel, p["ctx"], eid, p["cost"], p["detects"], seed=s)
            rk = [t for t in sel(p["ctx"], eid, float("inf"), seed=s) if t in p["cost"]]
            seeds.append(dict(auc=em.auc_detection_vs_budget, det20=em.detection_at_fraction[0.2],
                              apfdc=apfdc(rk, p["cost"], p["detects"])))
        rnd[eid] = seeds
        row["random"] = {k: float(np.mean([x[k] for x in seeds])) for k in ("auc", "det20", "apfdc")}
        row["random_20seed_auc"] = float(np.mean([x["auc"] for x in seeds[:20]]))
        per[eid] = row
    return pay, ids, per, rnd


def boot_mean_ci(v, n, seed, lo=2.5, hi=97.5):
    rng = np.random.default_rng(seed); v = np.asarray(v, float)
    m = v[rng.integers(0, len(v), (n, len(v)))].mean(axis=1)
    return [float(np.percentile(m, lo)), float(np.percentile(m, hi))]


def bayes_boot(d, n=20000, seed=0):
    rng = np.random.default_rng(seed); d = np.asarray(d, float)
    return rng.dirichlet(np.ones(len(d)), n) @ d


def tost_paired(d, m):
    d = np.asarray(d, float); n = len(d); mu = d.mean(); se = d.std(ddof=1) / np.sqrt(n)
    if se == 0:
        p = 0.0 if abs(mu) < m else 1.0
        return dict(p_lower=p, p_upper=p, p_tost=p)
    p_lo = float(tdist.sf((mu + m) / se, n - 1))   # H0: mean <= -m
    p_hi = float(tdist.cdf((mu - m) / se, n - 1))  # H0: mean >= +m
    return dict(p_lower=p_lo, p_upper=p_hi, p_tost=max(p_lo, p_hi))


def equivalence(d):
    d = np.array(d, float)
    ci90 = boot_mean_ci(d, 20000, 0, 5, 95)
    post = bayes_boot(d)
    return dict(n_events=len(d), n_zero_diff=int(np.sum(np.abs(d) < 1e-12)),
                n_positive=int(np.sum(d > 1e-12)), n_negative=int(np.sum(d < -1e-12)),
                mean_diff=float(d.mean()), bootstrap_ci90=ci90,
                ci90_within_margin={str(m): bool(ci90[0] > -m and ci90[1] < m) for m in MARGINS},
                tost_paired_t={str(m): tost_paired(d, m) for m in MARGINS},
                bayesian_bootstrap=dict(posterior_mean=float(post.mean()),
                                        cri95=[float(np.percentile(post, 2.5)), float(np.percentile(post, 97.5))],
                                        p_abs_mean_lt_margin={str(m): float(np.mean(np.abs(post) < m)) for m in MARGINS}))


def main():
    prev = json.load(open(REANALYSIS))
    res = {"description": (
        "POST-HOC analyses (not pre-registered) added for the revision; produced by scripts/revision_stats_extra.py. "
        "AUC = area under detection-vs-budget (cart.metrics.curves.event_metrics, full ranking, labelled per-unit costs). "
        "Paired comparisons use per-event AUC rounded to 4 decimals (r4) as in scripts/revision_reanalysis.py. "
        "A: random ordering over 100 seeds (0..99) on both cohorts; B: equivalence decomposed vs diversity_only; "
        "C: Bayesian-bootstrap practical significance of proposed (composite); D: resampling power of the Wilcoxon test "
        "at alpha=0.05/7 (Bonferroni bound for the 7-comparison Holm family), ASSUMING that new events resemble the 19 observed "
        "scale-up events (events resampled with replacement from the observed paired differences); E: single-fault APFDc."),
        "conventions": {"rounding": "r4 (4 decimals) before differencing/testing", "wilcoxon": "two-sided, zero_method='wilcox', method='auto'",
                        "random_per_event": "mean over seeds of per-seed AUC", "bootstrap": "percentile; rng numpy default_rng(0), fresh per quantity",
                        "bayesian_bootstrap": "Dirichlet(1,...,1) weights over events, 20000 draws, default_rng(0) fresh per quantity"}}
    data = {c: score_cohort(d) for c, d in COHORTS.items()}

    # ---------------- sanity checks against revision_reanalysis.json ----------------
    _, ids_s, per_s, _ = data["scaleup"]
    max_abs = max(abs(per_s[i][n]["auc"] - prev["per_event"][i][n]["auc"]) for i in ids_s for n in DET)
    max_abs_r20 = max(abs(per_s[i]["random_20seed_auc"] - prev["per_event"][i]["random"]["auc"]) for i in ids_s)
    mean20 = float(np.mean([per_s[i]["random_20seed_auc"] for i in ids_s]))
    look_prev = {(ref, r["vs"]): r for ref in prev["paired_tests"]["all19"] for r in prev["paired_tests"]["all19"][ref]}
    p_recomp = {f"{a}_vs_{b}": dict(recomputed=wilcox_p([per_s[i][a]["auc"] for i in ids_s], [per_s[i][b]["auc"] for i in ids_s]),
                                    reanalysis_json=look_prev[(a, b)]["p"]) for a, b in FAMILY7 if b != "random"}
    res["sanity_checks"] = dict(
        scaleup_deterministic_per_event_auc_max_abs_diff_vs_reanalysis=max_abs,
        scaleup_random_20seed_per_event_auc_max_abs_diff_vs_reanalysis=max_abs_r20,
        scaleup_random_20seed_mean=mean20, reanalysis_random_mean_all19=prev["means"]["all19"]["random"],
        nonrandom_family_raw_p=p_recomp)
    assert max_abs < 1e-12 and max_abs_r20 < 1e-12, "setup does not reproduce revision_reanalysis.json"

    # ---------------- A: random with 100 seeds ----------------
    A = {}
    for c, (pay, ids, per, rnd) in data.items():
        ev_mean = np.array([per[i]["random"]["auc"] for i in ids])
        seed_means = np.array([np.mean([rnd[i][s]["auc"] for i in ids]) for s in SEEDS100])
        seed_means20 = seed_means[:20]
        A[c] = dict(n_events=len(ids), n_seeds=100, mean_auc=float(ev_mean.mean()),
                    seed_interval95=[float(np.percentile(seed_means, 2.5)), float(np.percentile(seed_means, 97.5))],
                    seed_mean_range=[float(seed_means.min()), float(seed_means.max())],
                    event_bootstrap_ci95=boot_mean_ci(ev_mean, 5000, 0),
                    detection_at_20pct_budget=float(np.mean([per[i]["random"]["det20"] for i in ids])),
                    per_event_mean_auc={i: float(per[i]["random"]["auc"]) for i in ids},
                    twenty_seed=dict(mean_auc=float(seed_means20.mean()),
                                     seed_interval95=[float(np.percentile(seed_means20, 2.5)), float(np.percentile(seed_means20, 97.5))],
                                     event_bootstrap_ci95=boot_mean_ci([per[i]["random_20seed_auc"] for i in ids], 5000, 0)))
    A["scaleup"]["twenty_seed"]["from_revision_reanalysis_json"] = dict(
        mean_auc=prev["means"]["all19"]["random"], event_bootstrap_ci95=prev["random_event_bootstrap_ci"]["all19"]["ci95"])
    # paired tests involving random on scale-up, Holm within the 7-family
    raw = {k: look_prev[k]["p"] for k in FAMILY7 if k[1] != "random"}
    rows = {}
    for ref in ("proposed", "decomposed"):
        a = [per_s[i][ref]["auc"] for i in ids_s]; b = [per_s[i]["random"]["auc"] for i in ids_s]
        raw[(ref, "random")] = wilcox_p(a, b)
        rows[ref] = dict(mean_diff=float(np.mean(np.array(a) - np.array(b))), rank_biserial=rbc(a, b),
                         wins=int(sum(r4(x) > r4(y) for x, y in zip(a, b))), losses=int(sum(r4(x) < r4(y) for x, y in zip(a, b))),
                         ties=int(sum(r4(x) == r4(y) for x, y in zip(a, b))), p=raw[(ref, "random")])
    hp = dict(zip(FAMILY7, holm([raw[k] for k in FAMILY7])))
    A["scaleup_paired_tests_vs_random"] = {}
    for ref in ("proposed", "decomposed"):
        old = look_prev[(ref, "random")]
        A["scaleup_paired_tests_vs_random"][f"{ref}_vs_random"] = dict(
            seeds100={**rows[ref], "p_holm_family7": hp[(ref, "random")]},
            seeds20_from_revision_reanalysis_json={k: old[k] for k in ("mean_diff", "rank_biserial", "wins", "losses", "ties", "p", "p_holm_family7")})
    A["scaleup_family7_holm_with_100seed_random"] = {f"{a}_vs_{b}": dict(p=raw[(a, b)], p_holm=hp[(a, b)]) for a, b in FAMILY7}
    res["A_random_100_seeds"] = A

    # ---------------- B: equivalence decomposed vs diversity_only ----------------
    pay_s = data["scaleup"][0]
    d_all = [r4(per_s[i]["decomposed"]["auc"]) - r4(per_s[i]["diversity_only"]["auc"]) for i in ids_s]
    det_ids = [i for i in ids_s if any(pay_s[i]["detects"].values())]
    d_det = [r4(per_s[i]["decomposed"]["auc"]) - r4(per_s[i]["diversity_only"]["auc"]) for i in det_ids]
    res["B_equivalence_decomposed_vs_diversity_only"] = dict(
        difference="r4(decomposed) - r4(diversity_only)", margins=MARGINS,
        all19=equivalence(d_all), detectable17={**equivalence(d_det), "events": det_ids})

    # ---------------- C: practical significance of composite ----------------
    C = {}
    for other in ("diversity_only", "decomposed"):
        d = np.array([r4(per_s[i]["proposed"]["auc"]) - r4(per_s[i][other]["auc"]) for i in ids_s])
        post = bayes_boot(d)
        C[f"proposed_vs_{other}"] = dict(difference=f"r4(proposed) - r4({other})", n_events=len(d), mean_diff=float(d.mean()),
                                         posterior_mean=float(post.mean()),
                                         cri95=[float(np.percentile(post, 2.5)), float(np.percentile(post, 97.5))],
                                         p_mean_diff_lt_minus_0_02=float(np.mean(post < -0.02)), p_mean_diff_lt_0=float(np.mean(post < 0)))
    res["C_practical_significance_bayesian_bootstrap"] = C

    # ---------------- D: power ----------------
    D = {"alpha": ALPHA_BONF, "replicates": 5000, "n_grid": POWER_N,
         "assumption": "new events are exchangeable with (resemble) the 19 observed scale-up events: paired r4 differences are resampled with replacement",
         "all_zero_replicates": "counted as non-significant", "comparisons": {}}
    for a, b in [("proposed", "diversity_only"), ("decomposed", "proposed"), ("proposed", "cheapest_first")]:
        d = np.array([r4(per_s[i][a]["auc"]) - r4(per_s[i][b]["auc"]) for i in ids_s])
        rng = np.random.default_rng(0); table = {}
        for n in POWER_N:
            hits = 0
            for _ in range(5000):
                if wilcox_p_diff(d[rng.integers(0, len(d), n)]) < ALPHA_BONF: hits += 1
            table[str(n)] = hits / 5000
        D["comparisons"][f"{a}_vs_{b}"] = dict(observed_mean_diff=float(d.mean()), power=table,
                                               min_n_power_ge_0_8=next((n for n in POWER_N if table[str(n)] >= 0.8), None))
    res["D_power_wilcoxon_bonferroni"] = D

    # ---------------- E: APFDc ----------------
    E = {"definition": "single fault: APFDc = 1 - (C_before + 0.5*c_first)/C_total over the full ranking (labelled costs); 0 if no unit detects. Random = mean over seeds 0..99.",
         "note": "with one fault, APFDc = AUC + 0.5*c_first/C_total for detected events, so the two metrics differ only by half the first detecting unit's cost share"}
    for c, (pay, ids, per, rnd) in data.items():
        m_ap = {n: float(np.mean([per[i][n]["apfdc"] for i in ids])) for n in ALL}
        m_auc = {n: float(np.mean([per[i][n]["auc"] for i in ids])) for n in ALL}
        x = [per[i][n]["apfdc"] for n in ALL for i in ids]; y = [per[i][n]["auc"] for n in ALL for i in ids]
        rho, p = spearmanr(x, y)
        rk_ap = rankdata([-r4(m_ap[n]) for n in ALL], method="min"); rk_auc = rankdata([-r4(m_auc[n]) for n in ALL], method="min")
        E[c] = dict(n_events=len(ids), mean_apfdc=m_ap, mean_auc=m_auc,
                    spearman_apfdc_vs_auc_pooled=dict(rho=float(rho), p=float(p), n_pairs=len(x)),
                    rank_by_mean_apfdc={n: int(r) for n, r in zip(ALL, rk_ap)},
                    rank_by_mean_auc={n: int(r) for n, r in zip(ALL, rk_auc)},
                    rankings_equal=bool(np.array_equal(rk_ap, rk_auc)),
                    per_event_apfdc={i: {n: per[i][n]["apfdc"] for n in ALL} for i in ids})
    res["E_apfdc"] = E

    # F. Full paired table for the 7-comparison Holm family with random averaged over 100 seeds
    #    (scale-up cohort), so every number of the manuscript's paired table comes from one place.
    ra = json.loads((ROOT / "results" / "revision_reanalysis.json").read_text())["per_event"]
    ids19 = sorted(ra)
    rnd100 = res["A_random_100_seeds"]["scaleup"]["per_event_mean_auc"]
    val = lambda n: [r4(rnd100[i]) if n == "random" else r4(ra[i][n]["auc"]) for i in ids19]
    fam = [("proposed", "cheapest_first"), ("proposed", "diversity_only"), ("proposed", "decomposed"), ("proposed", "random"),
           ("decomposed", "cheapest_first"), ("decomposed", "diversity_only"), ("decomposed", "random")]
    rows = []
    for a, b in fam:
        x, y = val(a), val(b); d = [u - v for u, v in zip(x, y)]
        rows.append(dict(a=a, b=b, mean_diff=float(np.mean(d)), diff_ci95=list(boot_mean_ci(d, 5000, 0)),
                         rank_biserial=rbc(x, y), wins=int(sum(u > v for u, v in zip(x, y))),
                         ties=int(sum(u == v for u, v in zip(x, y))), losses=int(sum(u < v for u, v in zip(x, y))),
                         p=wilcox_p(x, y)))
    for row, h in zip(rows, holm([row["p"] for row in rows])):
        row["p_holm_family7"] = h
    res["F_paired_family7_random100"] = rows

    if OUT.exists():
        print("note: overwriting this script's own previous output", OUT)
    OUT.write_text(json.dumps(res, indent=1, default=float)); print("wrote", OUT)


if __name__ == "__main__":
    main()
