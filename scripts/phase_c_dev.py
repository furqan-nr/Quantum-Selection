"""Phase C DEVELOPMENT analysis on the existing (already labelled) cohorts -- EXPLORATORY, NOT confirmatory.

Purpose: choose and justify the deployable oracle-cost estimators and the COAST design before the Phase C
pre-registration, using only data that were labelled before Phase C (data/ = session A, data_scaleup/ = session B).
Nothing here is a test of a Phase C hypothesis; the dev-analogue hypothesis block only checks that the pre-registered
hypotheses are not true by construction.

Two directions, each genuinely out-of-session:
  A->B : estimator built from session A (data/, 9 events), evaluated on session B (data_scaleup/, 19 events)
  B->A : estimator built from session B, evaluated on session A
Estimators (cart.selectors.coast):
  previous : oracle cost = the unit's mean labelled oracle_cost_s in the OTHER session; transpilation part = the target
             cohort's own baseline profile CPU cost (pre-execution, exactly what the constant model already uses)
  analytic : oracle cost = AnalyticOracleModel fitted on the other session only (exact: c0 + theta*G*4^n;
             structural: c0 + theta*G; G = baseline transpiled size), same transpilation part
Selectors are evaluated with scripts/phase_c_analysis.evaluate_cohort (the frozen confirmatory code path; exact
injection = revision_costscale.py's *_exact construction). Budgets: rule E (5%/50% of the suite cost estimated from the
other session), rule T (5%/50% of its transpilation-only cost) and rule F (the target cohort's own frozen manuscript
budgets, configs/budgets*.yaml, for comparability with Table RQ4).

Run from repo root:  python scripts/phase_c_dev.py   ->  results/phase_c_dev.json
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("phase_c_analysis", ROOT / "scripts" / "phase_c_analysis.py")
PCA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PCA)

from cart.manifest.static_manifest import units_for                       # noqa: E402
from cart.selectors.coast import (OracleCostEstimator, effective_oracle_tier, session_unit_table)  # noqa: E402
from cart.selectors.cost_model import ORACLE_COST_EST                     # noqa: E402

DIRECTIONS = [("A_to_B", "data", "data_scaleup", "configs/budgets_scaleup.yaml"),
              ("B_to_A", "data_scaleup", "data", "configs/budgets.yaml")]
EXPENSIVE_S = 10.0


def accuracy(est: OracleCostEstimator, target_root: str, units: dict) -> dict:
    tb = session_unit_table(ROOT / target_root)
    ids = sorted(tb)
    an = OracleCostEstimator(est.prev_oracle_s, est.analytic, est.out_size, use_previous=False)
    res = {}
    for name, f in (("constant", lambda t: ORACLE_COST_EST[units[t].oracle_type]),
                    ("previous", lambda t: est.oracle_cost(units[t])),
                    ("analytic", lambda t: an.oracle_cost(units[t]))):
        row = {}
        for subset, sel in (("all_116", ids), ("expensive_oracle_gt_10s", [t for t in ids if tb[t]["oracle_cost_s"] > EXPENSIVE_S])):
            p = np.array([f(t) for t in sel]); y = np.array([tb[t]["oracle_cost_s"] for t in sel])
            pt = p + np.array([tb[t]["cpu_time_s"] for t in sel]); yt = np.array([tb[t]["total_cost_s"] for t in sel])
            row[subset] = {"n": len(sel),
                           "oracle_mape": float(np.mean(np.abs(p - y) / y)), "oracle_spearman": float(spearmanr(p, y).statistic),
                           "oracle_median_ratio_est_over_true": float(np.median(p / y)),
                           "total_mape": float(np.mean(np.abs(pt - yt) / yt)), "total_spearman": float(spearmanr(pt, yt).statistic),
                           "suite_oracle_est_s": float(p.sum()), "suite_oracle_true_s": float(y.sum())}
        res[name] = row
    res["per_expensive_unit"] = {t: {"true_oracle_s": tb[t]["oracle_cost_s"], "previous_s": est.oracle_cost(units[t]),
                                     "analytic_s": an.oracle_cost(units[t]), "tier": effective_oracle_tier(units[t]),
                                     "G": est.out_size.get(t)} for t in ids if tb[t]["oracle_cost_s"] > EXPENSIVE_S}
    res["tier_rule_check"] = {"n_exact_predicted": sum(effective_oracle_tier(units[t]) == "exact" for t in ids)}
    return res


def tier_rule_agreement(root: str, units: dict) -> dict:
    labs = json.loads((ROOT / root / "derived" / "labels.json").read_text())["labels"]
    agree = sum((effective_oracle_tier(units[r["test_id"]]) == "exact") == (r["oracle_strength"] == "exact") for r in labs)
    return {"n_rows": len(labs), "n_agree": int(agree)}


def summarise(c: dict) -> dict:
    ev = list(c["events"].values())
    out = {"mean_auc": {m: {n: float(np.mean([r["auc"][m][n] for r in ev])) for n in ev[0]["auc"][m]} for m in ev[0]["auc"]},
           "budgets": {}}
    for key in ev[0]["budget"]:
        out["budgets"][key] = {"budget_s": ev[0]["budget"][key]["budget_s"]}
        for m in list(PCA.MODELS) + ["own"]:
            out["budgets"][key][m] = {n: {"frac_detected": float(np.mean([r["budget"][key][m][n]["detected"] for r in ev])),
                                          "mean_spent_over_budget": float(np.mean([r["budget"][key][m][n]["spent_over_budget"] for r in ev])),
                                          "max_spent_over_budget": float(np.max([r["budget"][key][m][n]["spent_over_budget"] for r in ev])),
                                          "mean_n_units": float(np.mean([r["budget"][key][m][n]["n_units"] for r in ev]))}
                                      for n in ev[0]["budget"][key][m]}
    return out


def main():
    t0 = time.time()
    units = {u.test_id: u for u in units_for(ROOT / "data")}
    out = {"exploratory": True, "generated_by": "scripts/phase_c_dev.py",
           "note": "Development analysis on already-labelled cohorts; used to design Phase C. Not confirmatory.",
           "tier_rule_agreement": {r: tier_rule_agreement(r, units) for r in ("data", "data_scaleup")},
           "reference_cross_event_loo_exact_mean_auc": {}, "directions": {}}
    ref = json.loads((ROOT / "results" / "revision_costscale.json").read_text())
    for lab in ("primary_9", "scaleup_19"):
        out["reference_cross_event_loo_exact_mean_auc"][lab] = {n: v["mean_auc"] for n, v in ref[lab]["s1_prioritisation"]["summary"]["loo_exact"].items()}
    for name, prev, tgt, bpath in DIRECTIONS:
        cm = PCA.freeze_cost_model([prev])
        est = OracleCostEstimator.from_dict(cm["estimator"])
        frozen = yaml.safe_load((ROOT / bpath).read_text())["tiers"]
        budgets = {**cm["budgets"], "F": {"pr": float(frozen["pr"]["budget_s"]), "nightly": float(frozen["nightly"]["budget_s"])}}
        c = PCA.evaluate_cohort(ROOT / tgt, est, budgets, cm["prev_cpu_s"])
        out["directions"][name] = {"previous_session": prev, "target": tgt, "analytic_model": cm["estimator"]["analytic"],
                                   "speed_factor_raw": c["speed_factor_raw"], "speed_factor_applied": c["speed_factor_applied"],
                                   "budgets": c["budgets_applied"], "estimator_accuracy": accuracy(est, tgt, units),
                                   "summary": summarise(c),
                                   "dev_analogue_hypotheses": PCA.hypotheses({"dev": c}),
                                   "per_event": c["events"]}
        PCA.log(name, "done", f"{time.time() - t0:.0f}s")
    out["runtime_s"] = time.time() - t0
    p = ROOT / "results" / "phase_c_dev.json"
    p.write_text(json.dumps(out, indent=1, default=float))
    PCA.log("wrote", p)


if __name__ == "__main__":
    main()
