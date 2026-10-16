"""Post-hoc budgeted-selection evaluation added in the Scientific Reports revision (NOT pre-registered).

The frozen headline evaluation ranks every selector with an infinite budget and cuts the ranking at a
fraction of the labelled cost. This script instead gives each selector a FINITE budget, as the methodology
describes, and reports detection, selected-set size and the real (labelled) cost actually spent.

Two cost regimes:
  frozen    budget = frozen configs/budgets*.yaml tier value (model-cost seconds, from calibrated costs).
            Selectors use the pre-declared cost model (baseline cost + constant oracle estimate).
  measured  budget = tier fraction x the event's labelled full-suite cost; selectors are given the
            measured per-unit total cost (upper bound for an oracle-cost-aware selector).
Also: epsilon / exploration-reserve sensitivity and component ablation of `proposed` under finite budgets.
Run from repo root:  PYTHONPATH=src python scripts/revision_budgeted.py
"""
from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
import numpy as np, yaml
from scipy.stats import binomtest
from cart.metrics.evaluate import _build_payloads
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S
from cart.selectors.cost_model import ORACLE_COST_EST
from cart.selectors.proposed import proposed_selector

ROOT = Path(__file__).resolve().parents[1]
SEEDS = list(range(20))
TIERS = {"pr": 0.05, "nightly": 0.50}


def budgets(data_dir):
    cfg = "budgets_scaleup.yaml" if data_dir == "data_scaleup" else "budgets.yaml"
    t = yaml.safe_load((ROOT / "configs" / cfg).read_text())["tiers"]
    return {"pr": float(t["pr"]["budget_s"]), "nightly": float(t["nightly"]["budget_s"])}


def measured_ctx(p):
    ctx = p["ctx"]
    bc = dict(ctx.baseline_costs)
    for t, c in p["cost"].items():
        bc[(p["event_id"], t)] = max(c - ORACLE_COST_EST.get(ctx.test_meta(t).oracle_type, 0.05), 1e-9)
    return replace(ctx, baseline_costs=bc)


def run_one(sel, ctx, p, budget, seed=0, **kw):
    chosen = [t for t in sel(ctx, p["event_id"], budget, seed=seed, **kw) if t in p["cost"]]
    full = sum(p["cost"].values())
    spent = sum(p["cost"][t] for t in chosen)
    return dict(det=any(p["detects"].get(t, False) for t in chosen), n=len(chosen), frac=spent / full, spent=spent)


def main():
    out = {}
    for data_dir, label in [("data", "primary_9"), ("data_scaleup", "scaleup_19")]:
        pay = _build_payloads(ROOT / data_dir, None, "all")
        bud = budgets(data_dir)
        detectable = [p["event_id"] for p in pay if any(p["detects"].values())]
        res = {"n_events": len(pay), "n_detectable": len(detectable), "budgets_s": bud, "regimes": {}}
        for regime in ["frozen", "measured"]:
            R = {}
            for tier, frac in TIERS.items():
                per = {n: {} for n in S}
                for p in pay:
                    ctx = p["ctx"] if regime == "frozen" else measured_ctx(p)
                    b = bud[tier] if regime == "frozen" else frac * sum(p["cost"].values())
                    for n, sel in S.items():
                        rs = [run_one(sel, ctx, p, b, seed=s) for s in (SEEDS if n == "random" else [0])]
                        per[n][p["event_id"]] = {k: float(np.mean([r[k] for r in rs])) for k in ("det", "n", "frac", "spent")}
                summ = {}
                for n in S:
                    d = per[n]
                    summ[n] = dict(detect_all=float(np.mean([d[e]["det"] for e in d])),
                                   detect_detectable=float(np.mean([d[e]["det"] for e in detectable])) if detectable else None,
                                   mean_tests=float(np.mean([d[e]["n"] for e in d])),
                                   mean_cost_fraction=float(np.mean([d[e]["frac"] for e in d])),
                                   mean_spent_s=float(np.mean([d[e]["spent"] for e in d])))
                pair = {}
                for a, b2 in [("proposed", "diversity_only"), ("decomposed", "diversity_only"), ("decomposed", "proposed"),
                              ("proposed", "cheapest_first"), ("decomposed", "cheapest_first")]:
                    w = sum(per[a][e]["det"] > per[b2][e]["det"] + 1e-9 for e in per[a])
                    l = sum(per[a][e]["det"] < per[b2][e]["det"] - 1e-9 for e in per[a])
                    pv = float(binomtest(int(w), int(w + l), 0.5).pvalue) if w + l else 1.0
                    pair[f"{a}_vs_{b2}"] = dict(wins=int(w), losses=int(l), ties=int(len(per[a]) - w - l), sign_test_p=pv)
                R[tier] = dict(summary=summ, paired=pair, per_event=per)
            res["regimes"][regime] = R
        sens = {}
        for tier in TIERS:
            for eps in (0.01, 0.05, 0.10):
                for rf in (0.10, 0.15, 0.20):
                    rs = [run_one(proposed_selector, p["ctx"], p, bud[tier], eps_override=eps, reserve_frac=rf) for p in pay]
                    sens[f"{tier}|eps={eps}|reserve={rf}"] = dict(detect_all=float(np.mean([r["det"] for r in rs])),
                                                                 mean_tests=float(np.mean([r["n"] for r in rs])),
                                                                 mean_cost_fraction=float(np.mean([r["frac"] for r in rs])))
        res["proposed_sensitivity_frozen_budgets"] = sens
        abl = {}
        for tier in TIERS:
            for comp in [(), ("novelty",), ("change_stage",), ("oracle_confidence",), ("impact_prior",), ("cost",)]:
                rs = [run_one(proposed_selector, p["ctx"], p, bud[tier], ablate=comp) for p in pay]
                abl[f"{tier}|{'+'.join(comp) or 'full'}"] = dict(detect_all=float(np.mean([r["det"] for r in rs])),
                                                                 mean_tests=float(np.mean([r["n"] for r in rs])))
        res["proposed_ablation_frozen_budgets"] = abl
        out[label] = res
    (ROOT / "results" / "revision_budgeted.json").write_text(json.dumps(out, indent=1))
    print("wrote results/revision_budgeted.json")


if __name__ == "__main__":
    main()
