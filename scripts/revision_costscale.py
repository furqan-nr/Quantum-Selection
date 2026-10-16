"""Post-hoc cost-model / cost-scale analyses (NOT pre-registered). Uses cached labels only; no transpilation,
no frozen file is modified. Every number here is an exploratory, post-hoc analysis of the frozen corpora.

Cohorts: data/ (primary, 9 mutation events) and data_scaleup/ (scale-up, 19 mutation events), 116 units each.

Ranking-cost models (what the selectors SEE when ranking; evaluation always charges the LABELLED cost
total_cost_s of each unit in that event):
  constant : the frozen context, unchanged. expected_cost = baseline CPU transpilation cost (profiles.json)
             + a pre-declared constant oracle estimate (cost_model.ORACLE_COST_EST).
  loo      : each unit's cost = mean labelled total_cost_s of that unit on the OTHER events of the same cohort
             (leave-one-event-out; deployable). Injected exactly as in scripts/revision_extra.py:
             baseline_costs[(event, unit)] = max(est - ORACLE_COST_EST[oracle_type], 1e-9), so that
             expected_cost == est (except where the clamp binds; counted and reported).
  measured : the event's own labelled total_cost_s, injected the same way (an oracle upper bound; not deployable).
  NOTE: cheapest_first / diversity_only (and history_only / change_stage) rank by ctx.baseline_cost, i.e. by
  est - ORACLE_COST_EST under loo/measured, while proposed / decomposed / the composite variants rank by
  expected_cost (= est). This is inherited from the revision_extra.py construction and is reported, not changed.
  NOTE 2: the 1e-9 floor binds for 60 of 116 units in every event of both cohorts (units cheaper than their oracle
  constant), so under loo/measured those units get baseline_cost 1e-9 (all tied) and expected_cost = the oracle
  constant, NOT their estimate. Two additional models therefore remove the floor:
  loo_exact / measured_exact : baseline_costs = est, evaluated with every ORACLE_COST_EST entry temporarily set to 0
             in memory (model_env), so baseline_cost == expected_cost == est for every unit and every selector.
  loo / measured are kept because they are what revision_extra.py used (and what the sanity check reproduces).

Sections (keys of results/revision_costscale.json):
  s1_prioritisation      : per event x model x selector: prioritisation-view AUC (budget = inf; prefixes charged the
                           labelled cost), tests-to-first-detection (1-based rank, len+1 if none) and labelled seconds
                           up to and including the first detecting unit. Selectors: cheapest_first, diversity_only,
                           decomposed, proposed, random (mean over seeds 0..99), proposed_no_severity
                           (ablate=("impact_prior",)), additive, lex_severity_first, lex_diversity_first (the last three
                           imported from scripts/revision_extra.py; they read costs via expected_cost, so they see the
                           injected costs).
  s2_paired_tests        : scale-up cohort, each model: proposed vs diversity_only, decomposed vs proposed,
                           decomposed vs diversity_only. Mean difference, wins/ties/losses at 4 decimals (r4),
                           two-sided Wilcoxon (zero_method wilcox and pratt), exact two-sided sign test, paired
                           sign-flip permutation test of the mean difference (exact if <=20 nonzero, else 100000 flips,
                           seed 0). All tests use r4-rounded AUCs, as in scripts/revision_reanalysis.py.
  s3_mechanism           : constant model, proposed and diversity_only: rank of first detecting unit and the units ranked
                           before it with labelled cost > 10 s; fraction of pre-detection labelled cost that comes from
                           units whose labelled cost exceeds 100x their constant-model expected cost.
  s4_cost_decomposition  : per event: transpilation (cpu_time_s) vs oracle_cost_s share of labelled suite cost; top-4 /
                           top-8 unit share; share on units that never attribute a detection in any cohort event;
                           verification that the transpilation component equals the calibrated BASELINE profile cost
                           (cost_median_s), i.e. whether candidate (mutant) transpilation is charged.
  s5_frozen_budgets      : rank and select greedily within the FROZEN pr / nightly budget in seconds as measured by each
                           cost model (selector called with budget_s = frozen budget and the injected ctx); the selected
                           set is charged its labelled cost. Random: seeds 0..19.
  s6_decomposed_vs_diversity : per event: Kendall tau and #differing positions between decomposed and diversity_only
                           full rankings; #greedy steps at which decomposed's severity tie-break changes the pick
                           (local copy of decomposed_selector with/without the -severity key term; src untouched).
  s7_operator_classes    : scale-up: gate-insertion events ("insert-redundant" in event_id) vs others, mean AUC per
                           selector under the constant, loo and loo_exact models.
  All of s1, s2, s5, s6 are reported for all five models (constant, loo, measured, loo_exact, measured_exact).
  sanity_checks          : constant-model AUCs vs results/revision_reanalysis.json and results/revision_extra.json;
                           reproduction of revision_extra.py's LOO finite-budget table with this script's LOO context.

Run from repo root:  PYTHONPATH=src python scripts/revision_costscale.py
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import numpy as np
import scipy
import yaml
from scipy.stats import binomtest, kendalltau, wilcoxon

from cart.metrics.curves import event_metrics
from cart.metrics.evaluate import _build_payloads, _run_metrics
from cart.selectors import proposed as P
from cart.selectors.cost_model import ORACLE_COST_EST, expected_cost
from cart.selectors.decomposed import _severity
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S

ROOT = Path(__file__).resolve().parents[1]
INF = float("inf")
COHORTS = [("data", "primary_9", "configs/budgets.yaml"),
           ("data_scaleup", "scaleup_19", "configs/budgets_scaleup.yaml")]
MODELS = ["constant", "loo", "measured", "loo_exact", "measured_exact"]


@contextmanager
def model_env(model):
    """For the *_exact models, temporarily set every ORACLE_COST_EST entry to 0 (in memory only; the source file is
    untouched) so that baseline_cost == expected_cost == the estimate for EVERY unit and EVERY selector (no clamp, and
    cheapest_first/diversity_only rank by the same quantity as proposed/decomposed). Restored on exit."""
    if not model.endswith("_exact"):
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
RANDOM_SEEDS_S1 = list(range(100))
RANDOM_SEEDS_S5 = list(range(20))
EXPENSIVE_S = 10.0
MISEST_FACTOR = 100.0

# reuse revision_extra.py's combiner construction verbatim (import, not copy); do not write .pyc caches
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("revision_extra", ROOT / "scripts" / "revision_extra.py")
RX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RX)


def _no_severity(ctx, event_id, budget_s, *, seed=0, **_):
    return P.proposed_selector(ctx, event_id, budget_s, seed=seed, ablate=("impact_prior",))


SEL = {"cheapest_first": S["cheapest_first"], "diversity_only": S["diversity_only"],
       "decomposed": S["decomposed"], "proposed": S["proposed"], "proposed_no_severity": _no_severity,
       "additive": RX.make_variant("additive"), "lex_severity_first": RX.make_variant("lex_severity_first"),
       "lex_diversity_first": RX.make_variant("lex_diversity_first")}
DET = list(SEL)
ALL = DET + ["random"]
S5_SEL = ["cheapest_first", "diversity_only", "decomposed", "proposed", "proposed_no_severity", "random"]


def r4(x):
    return round(float(x), 4)


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


# ------------------------------------------------------------------------------------------------ cost models
def inject(ctx, event_id, est):
    """revision_extra.py construction: baseline_costs = est - oracle estimate (floored at 1e-9)."""
    bc = dict(ctx.baseline_costs)
    clamped = []
    for t, c in est.items():
        oe = ORACLE_COST_EST.get(ctx.test_meta(t).oracle_type, 0.05)
        if c - oe < 1e-9:
            clamped.append(t)
        bc[(event_id, t)] = max(c - oe, 1e-9)
    return replace(ctx, baseline_costs=bc), clamped


def model_contexts(pay):
    tot = {}
    for p in pay:
        for t, c in p["cost"].items():
            tot.setdefault(t, {})[p["event_id"]] = c
    out, clamp = {}, {}
    for p in pay:
        eid = p["event_id"]
        loo = {t: float(np.mean([c for e, c in tot[t].items() if e != eid])) for t in p["cost"]}
        cl, cl_c = inject(p["ctx"], eid, loo)
        cm, cm_c = inject(p["ctx"], eid, dict(p["cost"]))
        # exact variants: baseline_costs = estimate itself; used only inside model_env("*_exact") (oracle est = 0)
        bl, bm = dict(p["ctx"].baseline_costs), dict(p["ctx"].baseline_costs)
        for t in p["cost"]:
            bl[(eid, t)] = loo[t]; bm[(eid, t)] = p["cost"][t]
        out[eid] = {"constant": p["ctx"], "loo": cl, "measured": cm,
                    "loo_exact": replace(p["ctx"], baseline_costs=bl), "measured_exact": replace(p["ctx"], baseline_costs=bm)}
        clamp[eid] = {"loo": cl_c, "measured": cm_c}
        # verify expected_cost == injected estimate wherever the clamp does not bind
        for t in p["cost"]:
            if t not in cl_c:
                assert abs(expected_cost(cl, eid, t) - loo[t]) < 1e-9
            if t not in cm_c:
                assert abs(expected_cost(cm, eid, t) - p["cost"][t]) < 1e-9
        assert all(p["ctx"].test_meta(t).oracle_type in ORACLE_COST_EST for t in p["cost"])
        for m, est in (("loo_exact", loo), ("measured_exact", p["cost"])):
            with model_env(m):
                for t in p["cost"]:
                    assert expected_cost(out[eid][m], eid, t) == est[t] == out[eid][m].baseline_cost(eid, t)
    assert ORACLE_COST_EST == {"unitary": 0.05, "sampled_sv": 0.20, "property": 0.05, "structural": 0.01}
    return out, clamp, tot


# ------------------------------------------------------------------------------------------------ metrics
def first_detection(ranking, cost, detects):
    cum = 0.0
    for i, t in enumerate(ranking):
        cum += cost[t]
        if detects.get(t, False):
            return i + 1, cum, True
    return len(ranking) + 1, cum, False


def score_ranking(ranking, cost, detects):
    ranking = [t for t in ranking if t in cost]
    em = event_metrics(ranking, cost, detects)
    rank, sec, det = first_detection(ranking, cost, detects)
    assert det == em.detected and (not det or abs(sec - em.ttfr_cost) < 1e-9)
    return dict(auc=em.auc_detection_vs_budget, detected=det, tests_to_first_detection=rank,
                labelled_s_to_first_detection=sec, full_suite_s=em.full_suite_cost), ranking


# ------------------------------------------------------------------------------------------------ stats
def paired(a, b, n_perm=100000):
    a4, b4 = np.array([r4(x) for x in a]), np.array([r4(y) for y in b])
    d = a4 - b4
    nz = d[np.abs(d) > 1e-12]
    k = len(nz)
    res = dict(n=len(d), mean_diff=float(np.mean(np.array(a) - np.array(b))), mean_diff_r4=float(d.mean()),
               wins=int((d > 1e-12).sum()), ties=int((np.abs(d) <= 1e-12).sum()), losses=int((d < -1e-12).sum()))
    for zm in ("wilcox", "pratt"):
        if k == 0:
            res[f"wilcoxon_{zm}_p"] = 1.0
            continue
        try:
            res[f"wilcoxon_{zm}_p"] = float(wilcoxon(a4, b4, zero_method=zm, method="auto").pvalue)
        except ValueError as e:
            res[f"wilcoxon_{zm}_p"] = None
            res[f"wilcoxon_{zm}_note"] = str(e)
    res["sign_test_exact_p"] = float(binomtest(res["wins"], res["wins"] + res["losses"], 0.5).pvalue) if k else 1.0
    obs = abs(nz.sum())
    if k == 0:
        res.update(perm_p=1.0, perm_n_flips=0, perm_exact=True)
    elif k <= 20:
        signs = np.array(list(itertools.product([1.0, -1.0], repeat=k)))
        stats = np.abs(signs @ nz)
        res.update(perm_p=float(np.mean(stats >= obs - 1e-12)), perm_n_flips=int(len(signs)), perm_exact=True)
    else:
        rng = np.random.default_rng(0)
        signs = rng.choice([1.0, -1.0], size=(n_perm, k))
        stats = np.abs(signs @ nz)
        res.update(perm_p=float(np.mean(stats >= obs - 1e-12)), perm_n_flips=n_perm, perm_exact=False)
    res["n_nonzero"] = k
    return res


# ------------------------------------------------------------------------------------------------ decomposed copy
def decomposed_local(ctx, event_id, use_severity=True, count_changes=False):
    """Local copy of decomposed_selector with budget = inf. With use_severity=False the sort key omits -severity.
    If count_changes, at each greedy step also compute the pick the no-severity key would make from the SAME
    `remaining` list state, and count steps where they differ."""
    ids = ctx.candidate_test_ids()
    combo = {t: (ctx.test_meta(t).circuit_family, ctx.test_meta(t).backend_id) for t in ids}
    cost = {t: expected_cost(ctx, event_id, t) for t in ids}
    sev = {t: _severity(ctx, t) for t in ids}
    seen, chosen, remaining, changes, steps = set(), [], list(ids), 0, []
    while remaining:
        if count_changes:
            alt = sorted(remaining, key=lambda t: (combo[t] in seen, cost[t]))[0]
        if use_severity:
            remaining.sort(key=lambda t: (combo[t] in seen, cost[t], -sev[t]))
        else:
            remaining.sort(key=lambda t: (combo[t] in seen, cost[t]))
        picked = remaining[0]
        if count_changes and alt != picked:
            changes += 1
            steps.append(dict(step=len(chosen) + 1, picked=picked, without_tiebreak=alt,
                              cost_picked=cost[picked], cost_alt=cost[alt]))
        chosen.append(picked); seen.add(combo[picked]); remaining.remove(picked)
    return chosen, changes, steps


def kendall(r1, r2):
    pos2 = {t: i for i, t in enumerate(r2)}
    tau = kendalltau(list(range(len(r1))), [pos2[t] for t in r1]).statistic
    return float(tau), int(sum(1 for i, t in enumerate(r1) if r2[i] != t))


# ------------------------------------------------------------------------------------------------ main per cohort
def run_cohort(data_dir, label, budgets_path):
    t0 = time.time()
    pay = _build_payloads(ROOT / data_dir, None, "all")
    pay.sort(key=lambda p: p["event_id"])
    ids = [p["event_id"] for p in pay]
    byid = {p["event_id"]: p for p in pay}
    ctxs, clamp, tot = model_contexts(pay)
    labs = json.load(open(ROOT / data_dir / "derived" / "labels.json"))["labels"]
    lab = {(r["event_id"], r["test_id"]): r for r in labs}
    prof = {(q["event_id"], q["test_id"]): q for q in
            json.load(open(ROOT / data_dir / "profile_baseline" / "profiles.json"))["profiles"]}
    tiers = yaml.safe_load(open(ROOT / budgets_path))["tiers"]
    out = {"n_events": len(ids), "event_ids": ids,
           "clamp_counts": {e: {m: len(v) for m, v in clamp[e].items()} for e in ids}}

    # ---------------- S1 ----------------
    per, rankings = {}, {m: {n: {} for n in DET} for m in MODELS}
    for eid in ids:
        p = byid[eid]; per[eid] = {}
        for m in MODELS:
            ctx = ctxs[eid][m]; row = {}
            with model_env(m):
                for n in DET:
                    rk = SEL[n](ctx, eid, INF, seed=0)
                    row[n], rankings[m][n][eid] = score_ranking(rk, p["cost"], p["detects"])
                    em, _ = _run_metrics(SEL[n], ctx, eid, p["cost"], p["detects"])   # spec metric, cross-check
                    assert em.auc_detection_vs_budget == row[n]["auc"], (eid, m, n)
                rs = [score_ranking(SEL_RANDOM(ctx, eid, s), p["cost"], p["detects"])[0] for s in RANDOM_SEEDS_S1]
            row["random"] = dict(auc=float(np.mean([x["auc"] for x in rs])),
                                 auc_seeds0_19=float(np.mean([x["auc"] for x in rs[:20]])),
                                 detected=any(x["detected"] for x in rs),
                                 tests_to_first_detection=float(np.mean([x["tests_to_first_detection"] for x in rs])),
                                 labelled_s_to_first_detection=float(np.mean([x["labelled_s_to_first_detection"] for x in rs])),
                                 full_suite_s=rs[0]["full_suite_s"], n_seeds=len(rs))
            per[eid][m] = row
        log(label, eid, "s1 done", f"{time.time() - t0:.0f}s")
    summ = {}
    for m in MODELS:
        summ[m] = {}
        for n in ALL:
            v = [per[e][m][n] for e in ids]
            summ[m][n] = dict(mean_auc=float(np.mean([x["auc"] for x in v])),
                              n_detected=int(sum(bool(x["detected"]) for x in v)),
                              mean_tests_to_first_detection=float(np.mean([x["tests_to_first_detection"] for x in v])),
                              median_tests_to_first_detection=float(np.median([x["tests_to_first_detection"] for x in v])),
                              mean_labelled_s_to_first_detection_detected_events=(
                                  float(np.mean([x["labelled_s_to_first_detection"] for x in v if x["detected"]]))
                                  if any(x["detected"] for x in v) else None))
    out["s1_prioritisation"] = {"summary": summ, "per_event": per}

    # ---------------- S2 (computed for every cohort; the brief asks for scale-up) ----------------
    pairs = [("proposed", "diversity_only"), ("decomposed", "proposed"), ("decomposed", "diversity_only")]
    out["s2_paired_tests"] = {m: {f"{a}_vs_{b}": paired([per[e][m][a]["auc"] for e in ids],
                                                         [per[e][m][b]["auc"] for e in ids]) for a, b in pairs}
                              for m in MODELS}

    # ---------------- S3 ----------------
    mech, agg = {}, {}
    for n in ("proposed", "diversity_only"):
        pooled_pre, pooled_mis, fr = 0.0, 0.0, []
        d_pre, d_mis, d_fr = 0.0, 0.0, []
        mech[n] = {}
        for eid in ids:
            p = byid[eid]; ctx = ctxs[eid]["constant"]; rk = rankings["constant"][n][eid]
            rank, _, det = first_detection(rk, p["cost"], p["detects"])
            before = rk[:rank - 1]
            pre = sum(p["cost"][t] for t in before)
            mis_units = [t for t in before if p["cost"][t] > MISEST_FACTOR * expected_cost(ctx, eid, t)]
            mis = sum(p["cost"][t] for t in mis_units)
            exp = [dict(test_id=t, labelled_cost_s=p["cost"][t], model_expected_cost_s=expected_cost(ctx, eid, t),
                        oracle_strength=lab[(eid, t)]["oracle_strength"], oracle_type=ctx.test_meta(t).oracle_type,
                        n_qubits=ctx.test_meta(t).n_qubits)
                   for t in before if p["cost"][t] > EXPENSIVE_S]
            mech[n][eid] = dict(detected=det, first_detection_rank=rank, labelled_s_before_first_detection=pre,
                                labelled_s_before_from_misestimated_units=mis, n_misestimated_units_before=len(mis_units),
                                expensive_units_before=exp)
            pooled_pre += pre; pooled_mis += mis
            if pre > 0:
                fr.append(mis / pre)
            if det:
                d_pre += pre; d_mis += mis
                if pre > 0:
                    d_fr.append(mis / pre)
        agg[n] = dict(detected_events_only=dict(
                          n_events=int(sum(mech[n][e]["detected"] for e in ids)),
                          pooled_fraction=(d_mis / d_pre) if d_pre else None,
                          total_labelled_s_before_first_detection=d_pre, total_from_misestimated_units=d_mis,
                          mean_per_event_fraction=float(np.mean(d_fr)) if d_fr else None,
                          median_per_event_fraction=float(np.median(d_fr)) if d_fr else None,
                          n_events_with_nonzero_pre_cost=len(d_fr)),
                      including_undetected_events=dict(
                          note="undetected events contribute the whole ranking (= full labelled suite) as 'before'",
                          pooled_fraction=(pooled_mis / pooled_pre) if pooled_pre else None,
                          total_labelled_s_before_first_detection=pooled_pre, total_from_misestimated_units=pooled_mis,
                          mean_per_event_fraction=float(np.mean(fr)) if fr else None,
                          median_per_event_fraction=float(np.median(fr)) if fr else None,
                          n_events_with_nonzero_pre_cost=len(fr)),
                      n_events_with_expensive_unit_before=int(sum(bool(mech[n][e]["expensive_units_before"]) for e in ids)),
                      mean_first_detection_rank=float(np.mean([mech[n][e]["first_detection_rank"] for e in ids])))
    out["s3_mechanism"] = {"summary": agg, "per_event": mech}

    # ---------------- S4 ----------------
    never = {t for t in tot if not any(lab[(e, t)]["fault_id_detected"] for e in ids)}
    never_d = {t for t in tot if not any(byid[e]["detects"][t] for e in ids)}
    s4e, mx = {}, dict(total_minus_parts=0.0, cpu_vs_profile_median=0.0, cpu_vs_profile_cpu=0.0)
    for eid in ids:
        rows = [lab[(eid, t)] for t in byid[eid]["cost"]]
        T = sum(r["total_cost_s"] for r in rows)
        cpu = sum(r["cpu_time_s"] for r in rows); orc = sum(r["oracle_cost_s"] for r in rows)
        wall = sum(r["transpilation_time_s"] for r in rows)
        cs = sorted((r["total_cost_s"] for r in rows), reverse=True)
        cand = [r["details"].get("performance", {}).get("median_candidate_s") for r in rows]
        cand = [c for c in cand if c is not None]
        for r in rows:
            q = prof[(eid, r["test_id"])]
            mx["total_minus_parts"] = max(mx["total_minus_parts"], abs(r["total_cost_s"] - r["cpu_time_s"] - r["oracle_cost_s"]))
            mx["cpu_vs_profile_median"] = max(mx["cpu_vs_profile_median"], abs(r["cpu_time_s"] - q["cost_median_s"]))
            mx["cpu_vs_profile_cpu"] = max(mx["cpu_vs_profile_cpu"], abs(r["cpu_time_s"] - q["cpu_time_s"]))
        s4e[eid] = dict(labelled_suite_s=T, transpilation_cpu_s=cpu, oracle_s=orc, oracle_share=orc / T,
                        transpilation_share=cpu / T, top4_share=sum(cs[:4]) / T, top8_share=sum(cs[:8]) / T,
                        never_detecting_units_share=sum(r["total_cost_s"] for r in rows if r["test_id"] in never) / T,
                        baseline_wallclock_transpilation_s=wall,
                        candidate_median_transpilation_s_recorded_not_charged=sum(cand),
                        n_rows_with_candidate_timing=len(cand),
                        constant_model_expected_suite_s=sum(expected_cost(ctxs[eid]["constant"], eid, t) for t in byid[eid]["cost"]))
    cpu_range = max(max(lab[(e, t)]["cpu_time_s"] for e in ids) - min(lab[(e, t)]["cpu_time_s"] for e in ids) for t in tot)
    keys = ["oracle_share", "transpilation_share", "top4_share", "top8_share", "never_detecting_units_share"]
    out["s4_cost_decomposition"] = {
        "summary": {**{f"mean_{k}": float(np.mean([s4e[e][k] for e in ids])) for k in keys},
                    **{f"min_{k}": float(np.min([s4e[e][k] for e in ids])) for k in keys},
                    **{f"max_{k}": float(np.max([s4e[e][k] for e in ids])) for k in keys},
                    "mean_labelled_suite_s": float(np.mean([s4e[e]["labelled_suite_s"] for e in ids])),
                    "mean_transpilation_cpu_suite_s": float(np.mean([s4e[e]["transpilation_cpu_s"] for e in ids])),
                    "mean_constant_model_expected_suite_s": float(np.mean([s4e[e]["constant_model_expected_suite_s"] for e in ids])),
                    "mean_candidate_transpilation_recorded_s": float(np.mean([s4e[e]["candidate_median_transpilation_s_recorded_not_charged"] for e in ids])),
                    "n_never_detecting_units": len(never), "never_detecting_by_detects_flag_agrees": never == never_d,
                    "frozen_T_full_s": 2 * tiers["nightly"]["budget_s"]},
        "verification": {"max_abs_total_minus_cpu_plus_oracle": mx["total_minus_parts"],
                         "max_abs_label_cpu_vs_profile_cost_median_s": mx["cpu_vs_profile_median"],
                         "max_abs_label_cpu_vs_profile_cpu_time_s": mx["cpu_vs_profile_cpu"],
                         "max_range_of_label_cpu_time_s_across_events_per_unit": cpu_range},
        "per_event": s4e}
    log(label, "s3/s4 done")

    # ---------------- S5 ----------------
    s5 = {}
    for m in MODELS:
        s5[m] = {}
        for tier in ("pr", "nightly"):
            B = float(tiers[tier]["budget_s"]); res = {}
            for n in S5_SEL:
                rows = []
                for eid in ids:
                    p = byid[eid]; ctx = ctxs[eid][m]
                    seeds = RANDOM_SEEDS_S5 if n == "random" else [0]
                    rs = []
                    with model_env(m):
                        for s in seeds:
                            fn = SEL_RANDOM_B if n == "random" else SEL[n]
                            ch = [t for t in fn(ctx, eid, B, seed=s) if t in p["cost"]]
                            model_spent = sum(expected_cost(ctx, eid, t) for t in ch)
                            assert model_spent <= B + 1e-9, (m, tier, n, eid, model_spent)
                            spent = sum(p["cost"][t] for t in ch)
                            rs.append((float(any(p["detects"][t] for t in ch)), spent, spent / B, len(ch), model_spent))
                    rows.append(np.mean(rs, axis=0))
                rows = np.array(rows)
                res[n] = dict(frac_events_detected=float(rows[:, 0].mean()), mean_labelled_s=float(rows[:, 1].mean()),
                              mean_spent_over_budget=float(rows[:, 2].mean()), max_spent_over_budget=float(rows[:, 2].max()),
                              mean_n_units=float(rows[:, 3].mean()), mean_model_estimated_s=float(rows[:, 4].mean()))
            s5[m][tier] = {"budget_s": B, "by_selector": res}
        log(label, "s5", m, "done", f"{time.time() - t0:.0f}s")
    out["s5_frozen_budgets"] = s5

    # ---------------- S6 ----------------
    s6 = {}
    for m in MODELS:
        s6[m] = {}
        for eid in ids:
            ctx = ctxs[eid][m]
            with model_env(m):
                dec = [t for t in S["decomposed"](ctx, eid, INF) if t in byid[eid]["cost"]]
                loc, nchg, steps = decomposed_local(ctx, eid, True, True)
                nosev, _, _ = decomposed_local(ctx, eid, False)
            div = rankings[m]["diversity_only"][eid]
            assert loc == dec == rankings[m]["decomposed"][eid], (m, eid, "local copy does not reproduce decomposed_selector")
            tau, ndiff = kendall(dec, div)
            tau2, ndiff2 = kendall(dec, nosev)
            em = event_metrics(nosev, byid[eid]["cost"], byid[eid]["detects"])
            s6[m][eid] = dict(kendall_tau_decomposed_vs_diversity=tau, n_positions_differ_vs_diversity=ndiff,
                              first_differing_position_vs_diversity=next((i + 1 for i in range(len(dec)) if dec[i] != div[i]), None),
                              n_tiebreak_changes=nchg, tiebreak_change_steps=steps,
                              kendall_tau_vs_no_tiebreak_copy=tau2, n_positions_differ_vs_no_tiebreak_copy=ndiff2,
                              auc_decomposed=per[eid][m]["decomposed"]["auc"], auc_no_tiebreak_copy=em.auc_detection_vs_budget,
                              auc_diversity_only=per[eid][m]["diversity_only"]["auc"])
        log(label, "s6", m, "done")
    out["s6_decomposed_vs_diversity"] = {
        m: {"summary": dict(mean_kendall_tau=float(np.mean([v["kendall_tau_decomposed_vs_diversity"] for v in s6[m].values()])),
                            min_kendall_tau=float(np.min([v["kendall_tau_decomposed_vs_diversity"] for v in s6[m].values()])),
                            mean_positions_differ=float(np.mean([v["n_positions_differ_vs_diversity"] for v in s6[m].values()])),
                            total_tiebreak_changes=int(sum(v["n_tiebreak_changes"] for v in s6[m].values())),
                            n_events_with_tiebreak_change=int(sum(v["n_tiebreak_changes"] > 0 for v in s6[m].values())),
                            n_events_auc_differs_r4_vs_no_tiebreak=int(sum(r4(v["auc_decomposed"]) != r4(v["auc_no_tiebreak_copy"]) for v in s6[m].values())),
                            n_events_auc_differs_r4_vs_diversity=int(sum(r4(v["auc_decomposed"]) != r4(v["auc_diversity_only"]) for v in s6[m].values()))),
            "per_event": s6[m]} for m in MODELS}

    # ---------------- S7 ----------------
    ins = [e for e in ids if "insert-redundant" in e]; oth = [e for e in ids if e not in ins]
    out["s7_operator_classes"] = {
        "gate_insertion_events": ins, "other_events": oth,
        **{m: {"gate_insertion": {n: float(np.mean([per[e][m][n]["auc"] for e in ins])) for n in ALL} if ins else {},
               "other": {n: float(np.mean([per[e][m][n]["auc"] for e in oth])) for n in ALL}}
           for m in ("constant", "loo", "loo_exact")}}

    # ---------------- sanity: reproduce revision_extra LOO finite-budget table ----------------
    rx = {}
    for tier, frac in (("pr", 0.05), ("nightly", 0.50)):
        perx = {n: [] for n in ("cheapest_first", "diversity_only", "proposed", "decomposed", "random")}
        for eid in ids:
            p = byid[eid]; ctx = ctxs[eid]["loo"]
            est = {t: float(np.mean([c for e, c in tot[t].items() if e != eid])) for t in p["cost"]}
            budget = frac * sum(est.values()); full = sum(p["cost"].values())
            for n in perx:
                rs = []
                for s in (range(20) if n == "random" else [0]):
                    ch = [t for t in S[n](ctx, eid, budget, seed=s) if t in p["cost"]]
                    rs.append((any(p["detects"].get(t, False) for t in ch), sum(p["cost"][t] for t in ch) / full, len(ch)))
                perx[n].append(tuple(np.mean(rs, axis=0)))
        rx[tier] = {n: dict(detected=float(np.mean([x[0] for x in v])), real_cost_fraction=float(np.mean([x[1] for x in v])),
                            mean_tests=float(np.mean([x[2] for x in v]))) for n, v in perx.items()}
    out["_loo_fraction_budget_repro"] = rx
    out["_rankings_constant"] = {n: rankings["constant"][n] for n in ("proposed", "diversity_only", "decomposed")}
    log(label, "cohort done", f"{time.time() - t0:.0f}s")
    return out


def SEL_RANDOM(ctx, eid, seed):
    return S["random"](ctx, eid, INF, seed=seed)


def SEL_RANDOM_B(ctx, eid, budget, *, seed=0):
    return S["random"](ctx, eid, budget, seed=seed)


def sanity(res):
    checks = {}
    # (a) constant-model scale-up AUCs vs revision_reanalysis.json per_event (r4)
    R = json.load(open(ROOT / "results" / "revision_reanalysis.json"))["per_event"]
    su = res["scaleup_19"]["s1_prioritisation"]["per_event"]
    mism = []
    for e in su:
        for n in ("cheapest_first", "diversity_only", "proposed", "decomposed"):
            if r4(su[e]["constant"][n]["auc"]) != r4(R[e][n]["auc"]):
                mism.append((e, n, su[e]["constant"][n]["auc"], R[e][n]["auc"]))
        if r4(su[e]["constant"]["random"]["auc_seeds0_19"]) != r4(R[e]["random"]["auc"]):
            mism.append((e, "random(seeds0-19)", su[e]["constant"]["random"]["auc_seeds0_19"], R[e]["random"]["auc"]))
    checks["constant_vs_revision_reanalysis_scaleup"] = dict(n_compared=len(su) * 5, mismatches=mism, passed=not mism)
    # (b) constant-model AUCs (both cohorts, 4 base + 3 variants) vs revision_extra.json per_event_auc (r4)
    X = json.load(open(ROOT / "results" / "revision_extra.json"))
    mism, nc = [], 0
    for lab in ("primary_9", "scaleup_19"):
        pe = res[lab]["s1_prioritisation"]["per_event"]
        for e, row in X[lab]["per_event_auc"].items():
            for n, v in row.items():
                if n.startswith("_"):
                    continue
                nc += 1
                if r4(pe[e]["constant"][n]["auc"]) != r4(v):
                    mism.append((lab, e, n, pe[e]["constant"][n]["auc"], v))
    checks["constant_vs_revision_extra_per_event_auc"] = dict(n_compared=nc, mismatches=mism, passed=not mism)
    # (c) this script's LOO context reproduces revision_extra.py's LOO finite-budget table exactly
    mism, nc = [], 0
    for lab in ("primary_9", "scaleup_19"):
        mine = res[lab]["_loo_fraction_budget_repro"]; theirs = X[lab]["deployable_cost_estimator"]
        for tier in theirs:
            for n in theirs[tier]:
                for k, v in theirs[tier][n].items():
                    nc += 1
                    if abs(mine[tier][n][k] - v) > 1e-9:
                        mism.append((lab, tier, n, k, mine[tier][n][k], v))
    checks["loo_context_reproduces_revision_extra_deployable_table"] = dict(n_compared=nc, mismatches=mism, passed=not mism)
    checks["note"] = ("Deterministic AUCs were additionally cross-checked inline against cart.metrics.evaluate._run_metrics "
                      "(exact float equality, all models/selectors/events); the local decomposed copy was asserted to "
                      "reproduce decomposed_selector exactly under every model; injected expected_cost was asserted to equal "
                      "the LOO / measured estimate wherever the 1e-9 clamp does not bind; every finite-budget selection was "
                      "asserted to respect the frozen budget under the model's own expected_cost.")
    return checks


DESCRIPTIONS = {
    "s1_prioritisation": "Prioritisation view (budget=inf). auc = area under detection-vs-labelled-budget (1 - normalised "
                         "labelled cost to first detection; 0 if never detected). tests_to_first_detection is 1-based (len+1 "
                         "if none); labelled_s_to_first_detection includes the first detecting unit (full suite if none). "
                         "random: mean over seeds 0..99 (auc_seeds0_19 kept for the sanity check). Random ranking does not "
                         "depend on costs, so it is identical across models.",
    "s2_paired_tests": "Paired comparisons on r4-rounded per-event AUCs (scale-up is the requested cohort; primary also "
                       "given). mean_diff = mean(a-b) unrounded; wins = a>b. Wilcoxon two-sided, method='auto', with "
                       "zero_method wilcox (drops zero differences) and pratt. Sign test: exact binomial on wins vs losses. "
                       "Permutation: sign-flip of nonzero differences, statistic |sum d|, exact enumeration if <=20 nonzero.",
    "s3_mechanism": "Constant model. For proposed and diversity_only: rank of first detecting unit; units ranked before it "
                    f"with labelled cost > {EXPENSIVE_S} s (with constant-model expected cost, label oracle_strength, "
                    f"n_qubits). Summary: share of the labelled cost spent before first detection that comes from units "
                    f"whose labelled cost > {MISEST_FACTOR}x their constant-model expected cost (pooled over events, and "
                    "mean/median of per-event fractions over events with nonzero pre-detection cost). Headline: "
                    "detected_events_only. In including_undetected_events, an undetected event contributes the whole "
                    "ranking (the full labelled suite) as 'before', identically for every selector.",
    "s4_cost_decomposition": "Labelled total_cost_s per event split into cpu_time_s (baseline transpilation, the 'transpilation "
                             "component') and oracle_cost_s; top-4/top-8 shares; share on units whose label never attributes "
                             "this cohort's fault in any event. verification: total == cpu + oracle; label cpu_time_s == "
                             "baseline profile cost_median_s (so candidate/mutant transpilation is NOT charged; the candidate "
                             "transpilation medians recorded in details.performance are reported separately as "
                             "'recorded_not_charged'); range of label cpu_time_s across events per unit (0 => event-"
                             "independent cached baseline cost). frozen_T_full_s = 2 x nightly budget.",
    "s5_frozen_budgets": "Finite-budget selection with the frozen pr/nightly budgets in seconds. Each selector is called with "
                         "budget_s = frozen budget on the model-injected context (so the budget is enforced in the model's "
                         "own cost units); the selected set is then charged its labelled cost. proposed uses its default "
                         "reserve_frac=0.15 (the tier's exploration_reserve_frac is not read by proposed_selector). Random: "
                         "seeds 0..19, averaged within event first. Composite variants (additive/lex) are ranking-only and "
                         "are not included. mean_model_estimated_s is the spend as the model sees it.",
    "s6_decomposed_vs_diversity": "Per event and model (constant is the requested one): Kendall tau (scipy tau-b on "
                                  "positions) and number of differing positions between decomposed and diversity_only full "
                                  "rankings; n_tiebreak_changes = greedy steps at which decomposed's pick differs from the "
                                  "pick the same key without the -severity term would make from the same remaining-list "
                                  "state; plus a full no-tie-break copy ranking (tau, differing positions, AUC). Note: "
                                  "diversity_only sorts by baseline_cost while decomposed sorts by expected_cost "
                                  "(baseline + per-oracle-type constant), which can reorder units independently of severity.",
    "s7_operator_classes": "Scale-up only (primary has the same split given for completeness). Mean prioritisation AUC per "
                           "selector for gate-insertion events (event_id contains 'insert-redundant') vs all other events.",
    "sanity_checks": "See note inside.",
}


def main():
    t0 = time.time()
    res = {}
    for d, lab, b in COHORTS:
        res[lab] = run_cohort(d, lab, b)
    checks = sanity(res)
    out = {"post_hoc": True,
           "generated_by": "scripts/revision_costscale.py",
           "run_command": "PYTHONPATH=src python scripts/revision_costscale.py",
           "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__},
           "cost_models": {"constant": "frozen ctx: profile cpu cost + ORACLE_COST_EST constant",
                           "loo": "mean labelled total_cost_s on the other events of the cohort (deployable)",
                           "measured": "the event's own labelled total_cost_s (upper bound)",
                           "loo_exact / measured_exact": "same estimates, no 1e-9 floor: baseline_costs = est and all "
                                        "ORACLE_COST_EST entries set to 0 in memory while these models run, so every "
                                        "selector ranks / budgets by exactly est (see clamp_counts for why).",
                           "injection": "baseline_costs = max(est - ORACLE_COST_EST[oracle_type], 1e-9); cheapest_first and "
                                        "diversity_only rank by baseline_costs (= est - oracle constant) while proposed, "
                                        "decomposed and the composite variants rank by expected_cost (= est)."},
           "oracle_cost_est": ORACLE_COST_EST,
           "description": DESCRIPTIONS,
           "sanity_checks": checks}
    for lab in res:
        r = res[lab]
        out[lab] = {k: v for k, v in r.items() if not k.startswith("_")}
        out[lab]["loo_fraction_budget_reproduction"] = r["_loo_fraction_budget_repro"]
        out[lab]["constant_model_rankings"] = r["_rankings_constant"]
    out["runtime_s"] = time.time() - t0
    p = ROOT / "results" / "revision_costscale.json"
    p.write_text(json.dumps(out, indent=1, default=float))
    log("wrote", p, "sanity:", {k: v["passed"] for k, v in checks.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
