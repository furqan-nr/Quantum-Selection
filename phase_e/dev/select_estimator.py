"""Phase E estimator selection on DEVELOPMENT data = all Phase D data (PREREGISTRATION_PHASE_E.md, Section 4).

Phase D's assembled timing data (phase_d/data/assembled/, read only) are used here openly as development data: the
candidate unseen-test pricing rules are evaluated on Phase D's six distinct release pairs, their parameters are
tuned, the primary and secondary estimators are chosen by the pre-stated criterion below with leave-one-pair-out
(LOPO) validation, and the prior-predictive forecast of P1' and P2' is computed. Every evaluation calls the frozen
Phase E analysis functions (phase_e/analysis/phase_e_analysis.py), so the development numbers are computed exactly
as the confirmatory numbers will be. No Phase E study release is read.

Development pairs (Phase D's 6 distinct (P, B) pairs; suite = B's collect-only list WITHOUT Phase D's backported
tests, because Phase E has none; real cost = mean of B's two timing passes; every planned test charged):
  2.0.1->2.0.2, 2.0.3->2.1.0, 2.1.2->2.2.0rc1, 2.2.1->2.2.2, 2.4.2->2.5.0, 2.5.0->2.5.1

Selection criterion (lexicographic, applied to a set of pair rows; smaller is better):
  1. fails  = number of failed criteria among the four P1' criteria, P2', and the utilisation guard (mean spend ratio
              of cheapest_first >= 0.75 at both primary tiers; a guard against estimators that pass P1' by pricing
              unseen tests so high that they are never selected and the budget is left unused)
  2. risk   = P1' risk: max over the four criteria of max(mean / 1.25, max / 2.0)
  3. p2med  = median |suite-cost error|
  4. nparam = number of tuned parameters (simplicity)
Within a family, the parameter is tuned by the same criterion on the training pairs. Families are ranked by the
criterion on their LOPO held-out rows (each pair evaluated with the parameter tuned on the other five). The best
family is the PRIMARY estimator, the second best the SECONDARY; both are then refitted on all six pairs (the frozen
parameters). Phase D's registered rule is evaluated as the comparator.

Forecast (prior-predictive, Section 9 of the registration): pair bootstrap. Phase E has 7 patch pairs and 3 pairs
that cross a minor release. (a) LOPO pool: the six held-out rows of the primary family (3 patch, 3 minor); (b)
extended pool: every (P, B) pair of releases timed in Phase D with P < B within one minor (patch pool) or across one
minor (minor pool), evaluated with the frozen primary (in-sample for the six registered pairs, so optimistic). For each
pool, 20000 studies of 7 patch + 3 minor pairs drawn with replacement; P(P1'), P(P2') and their components.

    python3 phase_e/dev/select_estimator.py      -> phase_e/dev/estimator_selection.json
    python3 phase_e/dev/select_estimator.py --phase-d-p1-thresholds
                                                 -> phase_e/dev/estimator_selection_sensitivity_phase_d_p1_thresholds.json
                                                    (sensitivity: what the same procedure picks under Phase D's P1)
"""
from __future__ import annotations

import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "phase_e/analysis"))
import phase_e_analysis as A  # noqa: E402

DATA = R / "phase_d/data/assembled"
BP = "test/python/phase_d_backport/"
T = 60.0
FRACTIONS = [0.05, 0.25]
P1RULE = {"policies": ["cheapest_first", "coast_d"], "fractions": FRACTIONS, "mean_spend_ratio_max": 1.25,
          "single_pair_spend_ratio_max": 1.25}
P1_CONTINUITY = {"policies": ["cheapest_first", "coast_d"], "fractions": FRACTIONS, "mean_spend_ratio_max": 1.25,
                 "single_pair_spend_ratio_max": 2.0}
P2RULE = {"median_abs_rel_error_max": 0.15, "abs_rel_error_band": 0.25, "min_share_within_band": 0.8}
UTIL_MIN = 0.75
DEV_PAIRS = [("2.0.1", "2.0.2"), ("2.0.3", "2.1.0"), ("2.1.2", "2.2.0rc1"), ("2.2.1", "2.2.2"), ("2.4.2", "2.5.0"),
             ("2.5.0", "2.5.1")]
KIND = {("2.0.1", "2.0.2"): "patch", ("2.0.3", "2.1.0"): "minor", ("2.1.2", "2.2.0rc1"): "minor",
        ("2.2.1", "2.2.2"): "patch", ("2.4.2", "2.5.0"): "minor", ("2.5.0", "2.5.1"): "patch"}
TIMED = ["2.0.1", "2.0.2", "2.0.3", "2.1.0", "2.1.2", "2.2.0rc1", "2.2.1", "2.2.2", "2.4.2", "2.5.0", "2.5.1"]
N_BOOT = 20000


def base(stat_in, new, over="tests", **kw):
    s = {"min_seen": 3, "in_file": dict(stat_in), "new_file": {**new, "over": over}}
    s.update(kw)
    return s


MEAN, MED = {"stat": "mean"}, {"stat": "median"}


def Q(q):
    return {"stat": "quantile", "q": q}


# candidate families: name -> (number of tuned parameters, {parameter label: spec})
FAMILIES = {
    "F0_phase_d_median": (0, {"-": base(MED, MED)}),
    "F1_mean": (0, {"-": base(MEAN, MEAN)}),
    "F2_quantile": (1, {f"q={q}": base(Q(q), Q(q)) for q in (0.75, 0.9, 0.95, 0.99)}),
    "F3_mean_newfile_quantile": (1, {f"q={q}": base(MEAN, Q(q)) for q in (0.75, 0.9, 0.95, 0.99, 0.999)}),
    "F4_mean_newfile_mean_of_file_means": (0, {"-": base(MEAN, MEAN, over="file_means")}),
    "F5_scaled_mean": (1, {f"c={c}": base(MEAN, MEAN, scale=c) for c in (1.5, 2.0, 3.0, 5.0, 8.0)}),
    "F6_mean_floor_global_mean": (0, {"-": base({"stat": "mean", "floor_global": True}, MEAN)}),
    "F7_shrunk_mean": (1, {f"kappa={k}": base({"stat": "mean", "shrink_kappa": k}, MEAN) for k in (2, 5, 10, 25)}),
    "F8_quantile_newfile_mean_of_file_means": (1, {f"q={q}": base(Q(q), MEAN, over="file_means") for q in (0.75, 0.9, 0.95)}),
    "F10_quantile_newfile_p99": (1, {f"q_in={q}": base(Q(q), Q(0.99)) for q in (0.75, 0.9)}),
    "F9_scaled_median": (1, {f"c={c}": base(MED, MED, scale=c) for c in (2.0, 3.0, 5.0, 8.0)}),
}


# ------------------------------------------------------------------------------------------------ data
_cache: dict = {}


def run_tests(v: str, k: int):
    key = (v, k)
    if key not in _cache:
        p = DATA / f"run_w{v}_t{v}_pass{k}.json"
        _cache[key] = A._load(p)["tests"] if p.exists() else None
    return _cache[key]


def pair_inputs(P: str, B: str):
    pt = run_tests(P, 1)
    pdur = {t: (T if r["outcome"] == "timeout" else float(r["duration"])) for t, r in pt.items() if not t.startswith(BP)}
    col = DATA / f"collect_{B}.json"
    if col.exists():
        suite = [t for t in A.suite_from_collect(A._load(col)["collected"]) if not t.startswith(BP)]
    else:                                          # B timed once as a P release: its own record order
        suite = [t for t in run_tests(B, 1) if not t.startswith(BP)]
    passes = [run_tests(B, k) for k in (1, 2) if run_tests(B, k) is not None]
    real = {}
    for t in suite:
        ds = [(T if p[t]["outcome"] == "timeout" else float(p[t]["duration"])) for p in passes if t in p]
        real[t] = sum(ds) / len(ds) if ds else 0.0
    return suite, pdur, real, len(passes)


def row(P, B, spec):
    suite, pdur, real, _ = pair_inputs(P, B)
    return A.evaluate_estimator(suite, pdur, real, spec, 1.0, FRACTIONS)


# ------------------------------------------------------------------------------------------------ criterion
def criterion(rows: list[dict], nparam: int):
    p1 = A.decide_p1(rows, P1RULE)
    p2 = A.decide_p2([r["suite_cost_rel_error"] for r in rows], P2RULE)
    util = [statistics.mean(r["tiers"][str(f)]["cheapest_first"]["spend_ratio"] for r in rows) for f in FRACTIONS]
    fails = sum(1 for v in p1["criteria"].values() if not v["holds"]) + (0 if p2["supported"] else 1) \
        + sum(1 for u in util if u < UTIL_MIN)
    risk = A.p1_risk(p1, P1RULE)
    cont = A.decide_p1(rows, P1_CONTINUITY)
    key = (fails, round(risk, 6), round(p2["median_abs_rel_error"], 6), nparam)
    return key, {"fails": fails, "P1prime_risk": round(risk, 4), "P1prime": {k: {"mean": v["mean"], "max": v["max"],
                 "holds": v["holds"]} for k, v in p1["criteria"].items()}, "P2prime": {k: p2[k] for k in (
                 "median_abs_rel_error", "share_within_band", "supported", "strict_every_pair_within_band")},
                 "utilisation_mean_spend_ratio_cheapest_first": [round(u, 4) for u in util],
                 "P1_continuity_phase_d_thresholds_holds": cont["supported"]}


def summary_row(r: dict) -> dict:
    return {"rel_error": r["suite_cost_rel_error"],
            **{f"{pol}@{f}": r["tiers"][str(f)][pol]["spend_ratio"] for f in FRACTIONS for pol in ("cheapest_first", "coast_d")},
            "unseen_part@0.25": r["tiers"]["0.25"]["cheapest_first"]["spend_ratio_unseen_part"],
            "n_unseen": r["source_counts"]["in_file"] + r["source_counts"]["new_file"],
            "unseen_selected_share@0.25": (r["tiers"]["0.25"]["cheapest_first"]["selected_unseen"]
                                           / max(1, r["source_counts"]["in_file"] + r["source_counts"]["new_file"])),
            "lane_cost_ratio@0.05": r["lane_cost_ratio"]["0.05"], "lane_cost_ratio@0.25": r["lane_cost_ratio"]["0.25"],
            "new_file_tests": r["source_counts"]["new_file"],
            "new_file_selected@0.25": r["tiers"]["0.25"]["cheapest_first"]["selected_new_file"],
            "seen_selected_share@0.25": ((r["tiers"]["0.25"]["cheapest_first"]["selected"] - r["tiers"]["0.25"]["cheapest_first"]["selected_unseen"])
                                         / max(1, r["source_counts"]["seen"]))}


# ------------------------------------------------------------------------------------------------ forecast
def extended_pairs():
    def mm(v):
        a, b = v.split(".")[:2]
        return int(a), int(b)
    out = []
    for i, P in enumerate(TIMED):
        for B in TIMED[i + 1:]:
            (a1, b1), (a2, b2) = mm(P), mm(B)
            if a1 != a2:
                continue
            if b1 == b2:
                out.append((P, B, "patch"))
            elif b2 - b1 == 1 or (P == "2.4.2" and b2 == 5):
                out.append((P, B, "minor"))
    return out


def shocked(r: dict, eps: float) -> dict:
    """The row with every real cost multiplied by exp(eps): spend ratios x exp(eps), est/real x exp(-eps)."""
    m = math.exp(eps)
    return {"suite_cost_rel_error": (1.0 + r["suite_cost_rel_error"]) / m - 1.0,
            "tiers": {f: {pol: {"spend_ratio": v["spend_ratio"] * m} for pol, v in t.items()} for f, t in r["tiers"].items()}}


def bootstrap(pool: dict[str, list[dict]], seed: int, tau: float = 0.0) -> dict:
    """Pair bootstrap; tau > 0: smoothed bootstrap, every drawn pair's real costs multiplied by exp(N(0, tau^2))
    (a release-wide drift not seen in the development pool)."""
    rng = random.Random(seed)
    res = {"P1prime": 0, "P2prime": 0, "both": 0, "P2_strict": 0}
    comp = {f"{pol}@{f}": 0 for f in FRACTIONS for pol in ("cheapest_first", "coast_d")}
    for _ in range(N_BOOT):
        rows = [rng.choice(pool["patch"]) for _ in range(7)] + [rng.choice(pool["minor"]) for _ in range(3)]
        if tau > 0:
            rows = [shocked(r, rng.gauss(0.0, tau)) for r in rows]
        p1 = A.decide_p1(rows, P1RULE)
        p2 = A.decide_p2([r["suite_cost_rel_error"] for r in rows], P2RULE)
        res["P1prime"] += p1["supported"]
        res["P2prime"] += p2["supported"]
        res["both"] += p1["supported"] and p2["supported"]
        res["P2_strict"] += p2["strict_every_pair_within_band"]
        for k, v in p1["criteria"].items():
            comp[k] += v["holds"]
    return {**{k: round(v / N_BOOT, 4) for k, v in res.items()}, "P1prime_components": {k: round(v / N_BOOT, 4) for k, v in comp.items()},
            "n_boot": N_BOOT, "seed": seed, "tau": tau, "pool_sizes": {k: len(v) for k, v in pool.items()}}


# ------------------------------------------------------------------------------------------------ main
def main() -> None:
    global P1RULE
    outname = "estimator_selection.json"
    if "--phase-d-p1-thresholds" in sys.argv:          # sensitivity: selection under Phase D's P1 thresholds (2.0 max)
        P1RULE = dict(P1_CONTINUITY)
        outname = "estimator_selection_sensitivity_phase_d_p1_thresholds.json"
    rows = {fam: {lab: [row(P, B, spec) for P, B in DEV_PAIRS] for lab, spec in specs.items()}
            for fam, (_, specs) in FAMILIES.items()}
    out = {"schema": "phase_e_estimator_selection/1", "dev_pairs": [f"{P}->{B}" for P, B in DEV_PAIRS],
           "criterion": "lexicographic (fails, P1' risk, median |P2 error|, n tuned parameters); see module docstring",
           "rules": {"P1prime": P1RULE, "P2prime": P2RULE, "utilisation_min": UTIL_MIN}, "families": {}}
    ranking = []
    for fam, (npar, specs) in FAMILIES.items():
        labs = list(specs)
        # in-sample per parameter value
        insample = {lab: criterion(rows[fam][lab], npar)[1] | {"per_pair": {f"{P}->{B}": summary_row(r) for (P, B), r in zip(DEV_PAIRS, rows[fam][lab])}}
                    for lab in labs}
        # LOPO
        held, chosen = [], []
        for h in range(len(DEV_PAIRS)):
            tr = [i for i in range(len(DEV_PAIRS)) if i != h]
            best = min(labs, key=lambda lab: (criterion([rows[fam][lab][i] for i in tr], npar)[0], labs.index(lab)))
            chosen.append(best)
            held.append(rows[fam][best][h])
        key, info = criterion(held, npar)
        full = min(labs, key=lambda lab: (criterion(rows[fam][lab], npar)[0], labs.index(lab)))
        out["families"][fam] = {"n_params": npar, "in_sample": insample,
                                "lopo": {"param_chosen_per_heldout_pair": dict(zip([f"{P}->{B}" for P, B in DEV_PAIRS], chosen)),
                                         "heldout_per_pair": {f"{P}->{B}": summary_row(r) for (P, B), r in zip(DEV_PAIRS, held)},
                                         **info},
                                "refit_all_six": full, "spec_refit": specs[full]}
        ranking.append((key, fam))
        out["families"][fam]["_heldout_rows"] = held
    ranking.sort()
    out["ranking_lopo"] = [{"family": f, "key": list(k)} for k, f in ranking]
    prim, sec = ranking[0][1], ranking[1][1]
    out["primary"] = {"family": prim, "param": out["families"][prim]["refit_all_six"], "spec": out["families"][prim]["spec_refit"]}
    out["secondary"] = {"family": sec, "param": out["families"][sec]["refit_all_six"], "spec": out["families"][sec]["spec_refit"]}
    # forecast
    held = out["families"][prim]["_heldout_rows"]
    lopo_pool = {"patch": [r for (P, B), r in zip(DEV_PAIRS, held) if KIND[(P, B)] == "patch"],
                 "minor": [r for (P, B), r in zip(DEV_PAIRS, held) if KIND[(P, B)] == "minor"]}
    ext = extended_pairs()
    ext_rows = {"patch": [], "minor": []}
    ext_list = []
    for P, B, kind in ext:
        r = row(P, B, out["primary"]["spec"])
        ext_rows[kind].append(r)
        ext_list.append({"pair": f"{P}->{B}", "kind": kind, **summary_row(r)})
    # drift scale for the smoothed bootstrap: SD over the six development pairs of the log real/est ratio of the
    # SEEN tests of the suite (release-wide drift of tests the estimator knows), computed from the raw inputs, robust scale
    logs = []
    for P, B in DEV_PAIRS:
        suite, pdur, real, _ = pair_inputs(P, B)
        seen = [t for t in suite if t in pdur]
        logs.append(math.log(sum(real[t] for t in seen) / sum(pdur[t] for t in seen)))
    med = statistics.median(logs)
    tau = 1.4826 * statistics.median(abs(x - med) for x in logs)   # robust (MAD) scale: the solovay_kitaev file
    # change of 2.0.3->2.1.0 (-1.17) is a file-level change, already in the pool, not a release-wide drift
    out["forecast"] = {"design": "7 patch + 3 minor pairs per simulated study, drawn with replacement",
                       "seen_log_drift_per_dev_pair": [round(x, 4) for x in logs], "tau": round(tau, 4),
                       "lopo_pool": bootstrap(lopo_pool, 20261019), "extended_pool": bootstrap(ext_rows, 20261020),
                       "lopo_pool_smoothed": bootstrap(lopo_pool, 20261023, tau),
                       "extended_pool_smoothed": bootstrap(ext_rows, 20261024, tau),
                       "lopo_pool_smoothed_2tau": bootstrap(lopo_pool, 20261025, 2 * tau),
                       "extended_pool_smoothed_2tau": bootstrap(ext_rows, 20261026, 2 * tau),
                       "extended_pairs": ext_list}
    # same forecast for the secondary and the comparator (information only)
    for name, fam in (("secondary", sec), ("phase_d_registered", "F0_phase_d_median")):
        h2 = out["families"][fam]["_heldout_rows"]
        pool = {"patch": [r for (P, B), r in zip(DEV_PAIRS, h2) if KIND[(P, B)] == "patch"],
                "minor": [r for (P, B), r in zip(DEV_PAIRS, h2) if KIND[(P, B)] == "minor"]}
        spec = out["families"][fam]["spec_refit"]
        er = {"patch": [], "minor": []}
        for P, B, kind in ext:
            er[kind].append(row(P, B, spec))
        out["forecast"][f"{name}_lopo_pool"] = bootstrap(pool, 20261021)
        out["forecast"][f"{name}_extended_pool"] = bootstrap(er, 20261022)
        out["forecast"][f"{name}_extended_pool_smoothed"] = bootstrap(er, 20261027, tau)
    for fam in out["families"]:
        out["families"][fam].pop("_heldout_rows")
    out["p1_rule_used_for_selection"] = P1RULE
    (R / "phase_e/dev" / outname).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({"ranking": out["ranking_lopo"], "primary": out["primary"], "secondary": out["secondary"],
                      "forecast_lopo": out["forecast"]["lopo_pool"], "forecast_ext": out["forecast"]["extended_pool"]}, indent=1))


if __name__ == "__main__":
    main()
