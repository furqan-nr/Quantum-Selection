"""FROZEN confirmatory analysis for Phase C (PREREGISTRATION_PHASE_C.md). Do not edit after the pre-registration
timestamp; its SHA-256 is recorded in PREREGISTRATION_PHASE_C.sha256.

Inputs
  --cohort NAME=ROOT   one or two Phase C data roots (C1 = Qiskit 2.4.2, C2 = Qiskit 2.2.3), each with the usual
                       events/, derived/labels.json, profile_baseline/profiles.json, manifest_static/.
  --prev ROOT          earlier labelled sessions that define the deployable estimator (confirmatory: data and
                       data_scaleup, i.e. sessions A and B).
  --cost-model PATH    frozen estimator + budgets (configs/phase_c_cost_model.json). In confirmatory mode the
                       estimator rebuilt from --prev must reproduce it exactly (asserted).
  --write-cost-model   pre-registration step: write the frozen cost model from --prev (write-once) and exit.
  --dry-run            development dry run: the estimator and budgets are rebuilt from --prev by the frozen rule
                       and --cost-model is ignored; the output is labelled DRY RUN.
  --out PATH           results/phase_c_confirmatory.json in the confirmatory run.

Cost models (what selectors SEE; every selection is CHARGED the labelled total_cost_s of its units)
  constant  : frozen context, ctx.baseline_cost (baseline profile CPU transpilation) + cost_model.ORACLE_COST_EST.
  previous  : est(u) = ctx.baseline_cost(u) + mean oracle_cost_s of u in the previous sessions (analytic fallback for
              units never measured). Injected exactly: baseline_costs = est with ORACLE_COST_EST temporarily 0 in memory
              (revision_costscale.py's *_exact construction), so every selector ranks and budgets by est.
  analytic  : est(u) = ctx.baseline_cost(u) + AnalyticOracleModel prediction (fitted on the previous sessions only;
              G = the unit's baseline transpiled size from the cohort's own profiles.json, else previous sessions').
  COAST always uses its own estimator (= previous, with the analytic fallback) on the unmodified context.

Budgets (frozen in --cost-model before any Phase C label): rule E (primary) pr/nightly = 5% / 50% of the full-suite
cost ESTIMATED from the previous sessions (sum over units of mean cpu_time_s + mean oracle_cost_s); rule T
(secondary, comparability with the manuscript) = 5% / 50% of the previous sessions' mean transpilation-only suite
cost (sum of mean cpu_time_s).

Roles of the outputs (PREREGISTRATION_PHASE_C.md, Section 8; revised after the pre-freeze red-team review):
  CONFIRMATORY (the only confirmatory claims): P1 (cost-estimate transfer) and P2 (budget compliance of deployable
      selection). Both depend on per-unit costs measured in the NEW labeling sessions (new machine; C2 also a new SDK
      version), which no pre-registration-time computation observed. Pre-declared decision rules, evaluated per
      cohort; a P is SUPPORTED iff every criterion holds in every labelled cohort.
  REGISTERED FORECAST CHECKS (not confirmatory): H1-H4, the selector comparisons. Their detection sets were largely
      observable before registration (transpilation-only firing sweep), and their outcomes were FORECAST from that
      sweep and published before any label (environment/phase_c/verification/sweep_forecast.json). Statistics are as
      originally designed: per-operator differences (mean over cohorts), one-sided exact binomial sign test (ties
      dropped), Holm over H1-H4; sign-flip permutation test of the mean as a secondary statistic. The output reports
      the realised result next to the registered forecast.
  MECHANISM CHECKS (near-certain by construction, never counted as evidence): constant-price overrun (M1), gap
      shrinkage under the previous-session estimator (M2).
Unit of analysis for H1-H4: the OPERATOR (mutation_family); the same operator on two SDK versions is not counted twice.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True

from cart.metrics.curves import event_metrics                         # noqa: E402
from cart.metrics.evaluate import _build_payloads                     # noqa: E402
from cart.events.table import load_events                             # noqa: E402
from cart.selectors import proposed as P                              # noqa: E402
from cart.selectors.cost_model import ORACLE_COST_EST, expected_cost  # noqa: E402
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S    # noqa: E402
from cart.selectors.coast import (OracleCostEstimator, coast_selector, estimator_from_sessions,  # noqa: E402
                                  speed_factor)
from cart.manifest.static_manifest import units_for                   # noqa: E402

INF = float("inf")
ALPHA = 0.05
PR_FRAC, NIGHTLY_FRAC = 0.05, 0.50
SPEND_OK = 1.25          # P2 / H3: mean real spend / budget must be <= 1.25
SPEND_MAX = 2.0          # P2: no single event may exceed 2x its budget
SUITE_ERR = 0.25         # P1: |estimated / realised suite oracle cost - 1| <= 0.25
EXP_MEDAPE = 0.25        # P1: median absolute % error on the expensive units <= 0.25
EXPENSIVE_PREV_S = 10.0  # P1: expensive units = previous-session oracle estimate >= 10 s (frozen cost model; 8 units)
OVERRUN = 10.0           # M1 (mechanism): constant-model mean real spend / pr budget exceeds 10
SHRINK = 0.50            # H2: the composite-diversity gap must shrink by >= 50%
NONINF = 0.01            # H3: COAST AUC non-inferiority margin vs the best baseline
P2_SELECTORS = (("previous", "cheapest_first"), ("previous", "diversity_only"), ("own", "coast"))
FORECAST = "environment/phase_c/verification/sweep_forecast.json"
RANDOM_SEEDS_AUC = list(range(100))
RANDOM_SEEDS_BUDGET = list(range(20))
BASELINES = ["random", "cheapest_first", "diversity_only", "history_only", "change_stage", "decomposed"]
MODELS = ["constant", "previous", "analytic"]
BUDGET_SELECTORS = ["random", "cheapest_first", "diversity_only", "decomposed", "proposed", "proposed_no_severity"]


def r4(x):
    return round(float(x), 4)


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@contextmanager
def zero_oracle_constants(active: bool):
    """In-memory only (source untouched): ORACLE_COST_EST -> 0 so baseline_cost == expected_cost == injected est."""
    if not active:
        yield
        return
    saved = dict(ORACLE_COST_EST)
    try:
        for k in ORACLE_COST_EST:
            ORACLE_COST_EST[k] = 0.0
        yield
    finally:
        ORACLE_COST_EST.clear()
        ORACLE_COST_EST.update(saved)


def _no_severity(ctx, eid, budget, *, seed=0, **_):
    return P.proposed_selector(ctx, eid, budget, seed=seed, ablate=("impact_prior",))


SEL = {"random": S["random"], "cheapest_first": S["cheapest_first"], "diversity_only": S["diversity_only"],
       "history_only": S["history_only"], "change_stage": S["change_stage"], "decomposed": S["decomposed"],
       "proposed": S["proposed"], "proposed_no_severity": _no_severity}


# --------------------------------------------------------------------------------------------- frozen cost model
def freeze_cost_model(prev_roots: list[str]) -> dict:
    """Frozen rule: estimator from the previous sessions + rule-E and rule-T budgets. Pure function of prev labels."""
    units = {u.test_id: u for u in units_for(ROOT / prev_roots[0])}
    est, pooled = estimator_from_sessions([ROOT / r for r in prev_roots], units)
    t_full_e = float(sum(v["cpu_time_s"] + v["oracle_cost_s"] for v in pooled.values()))
    t_full_t = float(sum(v["cpu_time_s"] for v in pooled.values()))
    return {"schema": "phase_c_cost_model/v1",
            "prev_roots": prev_roots,
            "prev_label_sha256": {r: sha256(ROOT / r / "derived" / "labels.json") for r in prev_roots},
            "n_units": len(pooled),
            "budgets": {"E": {"T_full_estimated_s": t_full_e, "pr": PR_FRAC * t_full_e, "nightly": NIGHTLY_FRAC * t_full_e},
                        "T": {"T_full_transpilation_s": t_full_t, "pr": PR_FRAC * t_full_t, "nightly": NIGHTLY_FRAC * t_full_t}},
            "prev_cpu_s": {t: v["cpu_time_s"] for t, v in sorted(pooled.items())},
            "estimator": est.to_dict()}


def models_equal(a: dict, b: dict) -> bool:
    def norm(x):
        return json.loads(json.dumps(x, sort_keys=True), parse_float=lambda s: round(float(s), 9))
    keys = ("budgets", "estimator", "prev_cpu_s")
    return norm({k: a[k] for k in keys}) == norm({k: b[k] for k in keys})


# --------------------------------------------------------------------------------------------- cohort evaluation
def _profile_field(root: Path, field: str) -> dict[str, float]:
    p = root / "profile_baseline" / "profiles.json"
    out: dict[str, list] = {}
    if p.exists():
        for q in json.loads(p.read_text())["profiles"]:
            if q.get(field) is not None:
                out.setdefault(q["test_id"], []).append(float(q[field]))
    return {t: float(np.median(v)) for t, v in out.items()}


def first_rank(ranking, detects):
    return next((i + 1 for i, t in enumerate(ranking) if detects.get(t, False)), len(ranking) + 1)


def evaluate_cohort(root: Path, est0: OracleCostEstimator, budgets0: dict, prev_cpu_s: dict) -> dict:
    """Machine-speed rule (frozen): k = coast.speed_factor(cohort baseline CPU, previous-session CPU); if k is outside
    [0.8, 1.25] the previous-session/analytic oracle estimates AND both budget rules are multiplied by k."""
    t0 = time.time()
    pay = sorted(_build_payloads(root, None, "all"), key=lambda p: p["event_id"])
    events = {e.event_id: e for e in load_events(root / "events" / "events.json")}
    sizes = _profile_field(root, "out_size")
    k_raw, k = speed_factor(_profile_field(root, "cpu_time_s"), prev_cpu_s)
    est = replace(est0, speed_factor=k)
    budgets = {r: {t: (v * k if t in ("pr", "nightly") else v) for t, v in b.items()} for r, b in budgets0.items()}
    an_est = OracleCostEstimator(est.prev_oracle_s, est.analytic, {**est.out_size, **sizes}, use_previous=False, speed_factor=k)
    out = {"root": str(root), "n_events": len(pay), "speed_factor_raw": k_raw, "speed_factor_applied": k,
           "speed_factor_source": "baseline-transpilation CPU cost of the cohort's profiles (fault-independent, "
                                  "measured by the engine before each unit's oracles); never oracle costs or labels",
           "budgets_applied": budgets, "events": {},
           "estimator_accuracy": estimator_accuracy(root, est, prev_cpu_s),
           "history_leakage_check": history_check(pay, events)}
    for p in pay:
        eid, ctx, cost, det = p["event_id"], p["ctx"], p["cost"], p["detects"]
        ids = list(cost)
        ctxs = {"constant": ctx}
        for m, e in (("previous", est), ("analytic", an_est)):
            bc = dict(ctx.baseline_costs)
            for t in ids:
                bc[(eid, t)] = float(ctx.baseline_cost(eid, t)) + e.oracle_cost(ctx.test_meta(t))
            ctxs[m] = replace(ctx, baseline_costs=bc)
        row = {"mutation_family": events[eid].mutation_family, "fault_type": events[eid].fault_type.value,
               "n_detecting_units": int(sum(det.values())), "full_suite_s": float(sum(cost.values())),
               "detecting_units": sorted(t for t, v in det.items() if v),
               "auc": {}, "first_rank": {}, "budget": {}}
        # ---------- prioritisation view
        for m in MODELS:
            row["auc"][m], row["first_rank"][m] = {}, {}
            with zero_oracle_constants(m != "constant"):
                for n, fn in SEL.items():
                    if n == "random":
                        aucs = [event_metrics([t for t in fn(ctxs[m], eid, INF, seed=s) if t in cost], cost, det).auc_detection_vs_budget
                                for s in RANDOM_SEEDS_AUC]
                        row["auc"][m][n] = float(np.mean(aucs))
                        continue
                    rk = [t for t in fn(ctxs[m], eid, INF, seed=0) if t in cost]
                    row["auc"][m][n] = float(event_metrics(rk, cost, det).auc_detection_vs_budget)
                    row["first_rank"][m][n] = first_rank(rk, det)
        for variant, kw in (("coast", {}), ("coast_no_tier_key", {"tier_key": False})):
            rk = [t for t in coast_selector(ctx, eid, INF, estimator=est, **kw) if t in cost]
            row["auc"].setdefault("own", {})[variant] = float(event_metrics(rk, cost, det).auc_detection_vs_budget)
            row["first_rank"].setdefault("own", {})[variant] = first_rank(rk, det)
        # ---------- finite budgets
        for rule in budgets:            # "E" (primary) and "T" (secondary); dev script may add more
            for tier in ("pr", "nightly"):
                B = float(budgets[rule][tier])
                cell = {}
                for m in MODELS:
                    cell[m] = {}
                    with zero_oracle_constants(m != "constant"):
                        for n in BUDGET_SELECTORS:
                            rs = []
                            for s in (RANDOM_SEEDS_BUDGET if n == "random" else [0]):
                                ch = [t for t in SEL[n](ctxs[m], eid, B, seed=s) if t in cost]
                                assert sum(expected_cost(ctxs[m], eid, t) for t in ch) <= B + 1e-9
                                spent = sum(cost[t] for t in ch)
                                rs.append((float(any(det[t] for t in ch)), spent / B, len(ch)))
                            a = np.mean(np.array(rs), axis=0)
                            cell[m][n] = {"detected": float(a[0]), "spent_over_budget": float(a[1]), "n_units": float(a[2])}
                cell["own"] = {}
                for variant, kw in (("coast", {}), ("coast_no_tier_key", {"tier_key": False})):
                    ch = [t for t in coast_selector(ctx, eid, B, estimator=est, **kw) if t in cost]
                    spent = sum(cost[t] for t in ch)
                    cell["own"][variant] = {"detected": float(any(det[t] for t in ch)), "spent_over_budget": spent / B,
                                            "n_units": float(len(ch))}
                row["budget"][f"{rule}_{tier}"] = {"budget_s": B, **cell}
        out["events"][eid] = row
        log(root.name, eid, f"{time.time() - t0:.0f}s")
    return out


def history_check(pay, events) -> dict:
    """Leakage check: number of (event, label-row) pairs a selector could use as 'history' (rows of OTHER events dated
    strictly before the event). Phase C events of a cohort share one date, so this must be 0."""
    n = 0
    for p in pay:
        d = events[p["event_id"]].event_date
        n += sum(1 for r in p["ctx"].history if r["event_id"] != p["event_id"] and r["event_date"] < d)
    return {"usable_history_rows": int(n)}


def estimator_accuracy(root: Path, est: OracleCostEstimator, prev_cpu_s: dict) -> dict:
    """P1 inputs: previous-session oracle estimate (speed rule applied) vs the REALISED per-unit mean oracle cost of
    this cohort (mean over its events). Expensive set fixed in advance from the frozen estimator (>= 10 s)."""
    from cart.selectors.coast import session_unit_table
    units = {u.test_id: u for u in units_for(root)}
    real = {t: v["oracle_cost_s"] for t, v in session_unit_table(root).items() if t in units}
    estd = {t: est.oracle_cost(units[t]) for t in real}
    const = {t: float(ORACLE_COST_EST[units[t].oracle_type]) for t in real}
    exp_ids = sorted(t for t in real if est.prev_oracle_s.get(t, 0.0) >= EXPENSIVE_PREV_S)
    ape = {t: abs(estd[t] - real[t]) / real[t] for t in exp_ids if real[t] > 0}
    s_est, s_real = sum(estd.values()), sum(real.values())
    return {"n_units": len(real), "expensive_units": exp_ids,
            "suite_oracle_estimated_s": s_est, "suite_oracle_realised_s": s_real,
            "suite_relative_error": (s_est / s_real - 1.0) if s_real > 0 else None,
            "expensive_ape": ape, "expensive_median_ape": float(np.median(list(ape.values()))) if ape else None,
            "constant_model_suite_relative_error": (sum(const.values()) / s_real - 1.0) if s_real > 0 else None}


def confirmatory(cohorts: dict) -> dict:
    """P1 and P2 (the confirmatory family). Pre-declared decision rules evaluated in EVERY labelled cohort."""
    P1 = {}
    for c, v in cohorts.items():
        a = v["estimator_accuracy"]
        P1[c] = {"suite_relative_error": a["suite_relative_error"], "expensive_median_ape": a["expensive_median_ape"],
                 "criteria": {"suite_abs_error_le_0.25": a["suite_relative_error"] is not None and abs(a["suite_relative_error"]) <= SUITE_ERR,
                              "expensive_median_ape_le_0.25": a["expensive_median_ape"] is not None and a["expensive_median_ape"] <= EXP_MEDAPE}}
    P2 = {}
    for c, v in cohorts.items():
        cells, crit = {}, {}
        for tier in ("pr", "nightly"):
            for m, n in P2_SELECTORS:
                xs = [r["budget"][f"E_{tier}"][m][n]["spent_over_budget"] for r in v["events"].values()]
                cells[f"{tier}/{n}"] = {"mean": float(np.mean(xs)), "max": float(np.max(xs))}
                crit[f"{tier}/{n}/mean_le_1.25"] = float(np.mean(xs)) <= SPEND_OK
                crit[f"{tier}/{n}/max_le_2.0"] = float(np.max(xs)) <= SPEND_MAX
        P2[c] = {"spend_over_budget": cells, "criteria": crit}
    out = {"P1": {"claim": "previous-session oracle-cost estimates transfer to a new labeling session (C1) and a new SDK "
                           "version (C2)", "per_cohort": P1},
           "P2": {"claim": "selection budgeted with the previous-session estimate respects rule-E budgets in real time",
                  "per_cohort": P2}}
    for k in ("P1", "P2"):
        out[k]["cohorts_evaluated"] = sorted(cohorts)
        out[k]["supported"] = bool(cohorts) and all(all(x["criteria"].values()) for x in out[k]["per_cohort"].values())
        out[k]["failed_criteria"] = {c: [n for n, ok in x["criteria"].items() if not ok] for c, x in out[k]["per_cohort"].items()}
    return out


def mechanism_checks(cohorts: dict) -> dict:
    """Near-certain by construction (reported, never counted as evidence): M1 constant-price overrun at the rule-E pr
    tier; M2 shrinkage of the composite-diversity gap under the previous-session estimator."""
    over = {c: {n: cohort_mean(v, lambda r, n=n: r["budget"]["E_pr"]["constant"][n]["spent_over_budget"])
                for n in ("cheapest_first", "diversity_only")} for c, v in cohorts.items()}
    return {"M1_constant_pr_E_mean_spend_over_budget": over,
            "M1_overrun_gt_10x_every_cohort_both_selectors": all(x > OVERRUN for v in over.values() for x in v.values())}


def forecast_agreement(cohorts: dict, H: dict, path: Path) -> dict | None:
    """Realised vs registered forecast: per-event Jaccard of detection sets, and per hypothesis forecast vs realised."""
    if not path.exists():
        return None
    fc = json.loads(path.read_text())
    jac = {}
    for c, v in cohorts.items():
        for eid, r in v["events"].items():
            f = fc.get("predicted_detecting_units", {}).get(eid)
            if f is None:
                continue
            a, b = set(r["detecting_units"]), set(f)
            jac[eid] = (len(a & b) / len(a | b)) if (a | b) else 1.0
    hyp = {}
    for k, h in H.items():
        fh = fc.get("forecast_hypotheses", {}).get(k)
        if fh:
            hyp[k] = {"forecast": {x: fh[x] for x in ("wins", "losses", "ties", "p_one_sided", "supported") if x in fh},
                      "realised": {x: h[x] for x in ("wins", "losses", "ties", "p_one_sided", "supported")},
                      "same_support_decision": fh.get("supported") == h["supported"]}
    return {"forecast_file": str(path), "forecast_sha256": sha256(path), "detection_set_jaccard": jac,
            "mean_jaccard": float(np.mean(list(jac.values()))) if jac else None, "hypotheses": hyp}


# --------------------------------------------------------------------------------------------- statistics
def perm_one_sided(d) -> float:
    """Exact one-sided sign-flip permutation test of mean(d) > 0 (all 2^k patterns; k = len(d) <= 20)."""
    d = np.asarray(d, float)
    k = len(d)
    if k == 0 or np.allclose(d, 0):
        return 1.0
    assert k <= 20, "exact enumeration only"
    signs = np.array(list(itertools.product([1.0, -1.0], repeat=k)))
    stats = signs @ d
    return float(np.mean(stats >= d.sum() - 1e-12))


def sign_one_sided(wins: int, losses: int) -> float:
    return float(binomtest(wins, wins + losses, 0.5, alternative="greater").pvalue) if wins + losses else 1.0


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, adj, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


def per_operator(cohorts: dict, getter) -> dict:
    """Mean over cohorts of getter(event_row) per mutation_family."""
    acc: dict[str, list] = {}
    for c in cohorts.values():
        for row in c["events"].values():
            acc.setdefault(row["mutation_family"], []).append(getter(row))
    return {k: float(np.mean(v)) for k, v in sorted(acc.items())}


def cohort_mean(c, getter):
    return float(np.mean([getter(r) for r in c["events"].values()]))


def _sign(d: dict) -> tuple[int, int, int, float]:
    w = sum(1 for v in d.values() if v > 1e-12)
    l_ = sum(1 for v in d.values() if v < -1e-12)
    return w, l_, len(d) - w - l_, sign_one_sided(w, l_)


def _test_block(name: str, statistic: str, d: dict) -> dict:
    w, l_, t, p = _sign(d)
    return {"statistic": statistic, "per_operator": d, "n_operators": len(d), "wins": w, "losses": l_, "ties": t,
            "mean": float(np.mean(list(d.values()))), "p_one_sided": p,
            "secondary_perm_p_one_sided": perm_one_sided(list(d.values()))}


def hypotheses(cohorts: dict) -> dict:
    """REGISTERED FORECAST CHECKS (not confirmatory): one-sided exact sign tests (ties dropped) on per-operator
    differences of r4-rounded AUCs; Holm over H1-H4. 'supported' iff Holm-adjusted p < 0.05 AND every listed condition
    holds. Mechanism checks (constant-price overrun; spend, now P2) are NOT conditions."""
    H = {}
    auc = lambda r, m, n: r4(r["auc"][m][n])                                                   # noqa: E731
    bud = lambda key, m, n, f: (lambda r: r["budget"][key][m][n][f])                           # noqa: E731
    pooled_mean = lambda g: float(np.mean([g(r) for c in cohorts.values() for r in c["events"].values()]))  # noqa: E731

    # H1: the cost confound replicates (constant oracle prices)
    H["H1"] = _test_block("H1", "AUC(diversity_only) - AUC(composite), constant model",
                          per_operator(cohorts, lambda r: auc(r, "constant", "diversity_only") - auc(r, "constant", "proposed")))
    per_c = {c: cohort_mean(v, lambda r: r["auc"]["constant"]["diversity_only"] - r["auc"]["constant"]["proposed"]) for c, v in cohorts.items()}
    H["H1"].update(per_cohort_mean_gap=per_c,
                   conditions={"gap_positive_in_every_cohort": all(v > 0 for v in per_c.values())})

    # H2: the deployable previous-session estimator removes most of the deficit and makes budgets meaningful
    H["H2"] = _test_block("H2", "AUC(composite, previous-session estimator) - AUC(composite, constant)",
                          per_operator(cohorts, lambda r: auc(r, "previous", "proposed") - auc(r, "constant", "proposed")))
    mgc = pooled_mean(lambda r: r["auc"]["constant"]["diversity_only"] - r["auc"]["constant"]["proposed"])
    mgp = pooled_mean(lambda r: r["auc"]["previous"]["diversity_only"] - r["auc"]["previous"]["proposed"])
    shrink = (1.0 - mgp / mgc) if mgc > 0 else None
    sp = {c: {n: cohort_mean(v, bud("E_pr", "previous", n, "spent_over_budget")) for n in ("cheapest_first", "diversity_only")}
          for c, v in cohorts.items()}
    for c, v in cohorts.items():
        sp[c]["coast"] = cohort_mean(v, bud("E_pr", "own", "coast", "spent_over_budget"))
    H["H2"].update(mean_gap_constant=mgc, mean_gap_previous=mgp, shrinkage=shrink, previous_pr_E_mean_spend_over_budget=sp,
                   conditions={"gap_constant_positive": mgc > 0, "shrinkage_ge_50pct": (shrink is not None and shrink >= SHRINK)})

    # H3: COAST beats the pre-specified composite as deployed, is non-inferior to the best baseline under the same
    # estimator, and exposes at least as many faults within budget as constant-priced diversity-only does over budget
    H["H3"] = _test_block("H3", "AUC(COAST, own estimator) - AUC(composite, constant)",
                          per_operator(cohorts, lambda r: auc(r, "own", "coast") - auc(r, "constant", "proposed")))
    pooled = {b: pooled_mean(lambda r, b=b: r["auc"]["previous"][b]) for b in BASELINES}
    best = max(BASELINES, key=lambda b: (pooled[b], b))
    ni = per_operator(cohorts, lambda r: auc(r, "own", "coast") - auc(r, "previous", best))
    det = {}
    for tier in ("pr", "nightly"):
        det[tier] = {"coast_own": float(sum(r["budget"][f"E_{tier}"]["own"]["coast"]["detected"] for c in cohorts.values() for r in c["events"].values())),
                     "diversity_constant": float(sum(r["budget"][f"E_{tier}"]["constant"]["diversity_only"]["detected"] for c in cohorts.values() for r in c["events"].values())),
                     "coast_mean_spend_over_budget": {c: cohort_mean(v, bud(f"E_{tier}", "own", "coast", "spent_over_budget")) for c, v in cohorts.items()}}
    H["H3"].update(best_baseline_previous=best, pooled_baseline_auc_previous=pooled, noninferiority_per_operator=ni,
                   noninferiority_mean=float(np.mean(list(ni.values()))), detection_E=det,
                   conditions={"noninferior_to_best_baseline_within_0.01": float(np.mean(list(ni.values()))) >= -NONINF,
                               "coast_detects_ge_diversity_constant_pr_and_nightly": all(v["coast_own"] >= v["diversity_constant"] for v in det.values()),
                               "coast_spend_le_1.25_every_cohort_both_tiers": all(x <= SPEND_OK for v in det.values() for x in v["coast_mean_spend_over_budget"].values())})

    # H4: the residual deficit under the deployable estimator is the severity term
    H["H4"] = _test_block("H4", "AUC(composite without severity) - AUC(composite), previous-session estimator",
                          per_operator(cohorts, lambda r: auc(r, "previous", "proposed_no_severity") - auc(r, "previous", "proposed")))
    H["H4"]["conditions"] = {}

    adj = holm({k: v["p_one_sided"] for k, v in H.items()})
    for k in H:
        H[k]["p_holm"] = adj[k]
        H[k]["supported"] = bool(adj[k] < ALPHA and all(H[k]["conditions"].values()))
    return H


def secondary_event_level(cohorts: dict) -> dict:
    """Pre-declared SECONDARY: the same four sign tests per cohort at the event level (no Holm, descriptive)."""
    defs = {"H1": ("constant", "diversity_only", "constant", "proposed"), "H2": ("previous", "proposed", "constant", "proposed"),
            "H3": ("own", "coast", "constant", "proposed"), "H4": ("previous", "proposed_no_severity", "previous", "proposed")}
    out = {}
    for c, v in cohorts.items():
        out[c] = {}
        for h, (m1, n1, m2, n2) in defs.items():
            d = {e: r4(r["auc"][m1][n1]) - r4(r["auc"][m2][n2]) for e, r in v["events"].items()}
            w, l_, t, p = _sign(d)
            out[c][h] = {"wins": w, "losses": l_, "ties": t, "p_one_sided": p, "mean": float(np.mean(list(d.values())))}
    return out


def exploratory(cohorts: dict) -> dict:
    """Pre-declared EXPLORATORY summaries (no confirmatory claim): mean AUC by model x selector per cohort, budgets
    under rules E and T, analytic-model results, COAST without the tier key."""
    out = {}
    for c, v in cohorts.items():
        ev = list(v["events"].values())
        out[c] = {"mean_auc": {m: {n: float(np.mean([r["auc"][m][n] for r in ev])) for n in ev[0]["auc"][m]} for m in ev[0]["auc"]},
                  "budgets": {key: {m: {n: {f: float(np.mean([r["budget"][key][m][n][f] for r in ev])) for f in ("detected", "spent_over_budget", "n_units")}
                                        for n in ev[0]["budget"][key][m]} for m in list(MODELS) + ["own"]}
                              for key in ev[0]["budget"]},
                  "n_events_detectable": int(sum(r["n_detecting_units"] > 0 for r in ev))}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", action="append", default=[], help="NAME=ROOT")
    ap.add_argument("--write-cost-model", action="store_true",
                    help="(pre-registration step only) write the frozen estimator + budgets from --prev to --cost-model and exit")
    ap.add_argument("--prev", action="append", default=None)
    ap.add_argument("--cost-model", default="configs/phase_c_cost_model.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="results/phase_c_confirmatory.json")
    ap.add_argument("--forecast", default=FORECAST, help="registered sweep forecast (agreement is reported if present)")
    a = ap.parse_args(argv)
    prev = a.prev or ["data", "data_scaleup"]
    t0 = time.time()
    rebuilt = freeze_cost_model(prev)
    if a.write_cost_model:
        p = ROOT / a.cost_model
        assert not p.exists(), f"{p} exists; the frozen cost model is write-once"
        p.write_text(json.dumps(rebuilt, indent=1, sort_keys=True))
        log("wrote frozen cost model", p, rebuilt["budgets"])
        return rebuilt
    assert a.cohort, "--cohort NAME=ROOT is required"
    if a.dry_run:
        cm = rebuilt
    else:
        cm = json.loads((ROOT / a.cost_model).read_text())
        assert models_equal(cm, rebuilt), "frozen cost model does not match the estimator rebuilt from --prev"
    est = OracleCostEstimator.from_dict(cm["estimator"])
    cohorts = {}
    for spec in a.cohort:
        name, root = spec.split("=", 1)
        cohorts[name] = evaluate_cohort(ROOT / root, est, cm["budgets"], cm["prev_cpu_s"])
    H = hypotheses(cohorts)
    fpath = Path(a.forecast) if Path(a.forecast).is_absolute() else ROOT / a.forecast
    res = {"dry_run": bool(a.dry_run), "generated_by": "scripts/phase_c_analysis.py",
           "cohorts_labelled": sorted(cohorts),
           "deviation_missing_cohort": sorted({"C1", "C2"} - set(cohorts)) if not a.dry_run else None,
           "confirmatory": confirmatory(cohorts),
           "mechanism_checks": mechanism_checks(cohorts),
           "forecast_agreement": forecast_agreement(cohorts, H, fpath),
           "leakage_checks": {k: {"history": v["history_leakage_check"], "speed_factor_source": v["speed_factor_source"]}
                              for k, v in cohorts.items()},
           "script_sha256": sha256(Path(__file__)), "cost_model": {k: cm[k] for k in ("prev_roots", "prev_label_sha256", "budgets")},
           "analytic_model": cm["estimator"]["analytic"], "cohorts": {k: {"root": v["root"], "speed_factor_raw": v["speed_factor_raw"],
                                                                    "speed_factor_applied": v["speed_factor_applied"],
                                                                    "budgets_applied": v["budgets_applied"],
                                                                    "estimator_accuracy": v["estimator_accuracy"]} for k, v in cohorts.items()},
           "registered_forecast_checks": H, "secondary_event_level": secondary_event_level(cohorts), "exploratory": exploratory(cohorts), "per_event": {k: v["events"] for k, v in cohorts.items()},
           "runtime_s": time.time() - t0}
    outp = Path(a.out) if Path(a.out).is_absolute() else ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(res, indent=1, default=float))
    log("wrote", outp, {k: res["confirmatory"][k]["supported"] for k in ("P1", "P2")},
        {k: (round(v["p_holm"], 4), v["supported"]) for k, v in H.items()})
    return res


if __name__ == "__main__":
    main()
