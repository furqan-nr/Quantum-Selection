"""Post-hoc analyses added for the Scientific Reports submission (NOT pre-registered). Uses cached labels only.

A. Stratification of per-event AUC by fault detectability (fraction of the 116 units that expose the fault).
B. Alternative combiners for the same risk_score inputs (additive; lexicographic severity-first; lexicographic
   diversity-first) in the prioritisation view, to separate "multiplicative scoring" from "ordering of signals".
C. A deployable cost estimator: each unit's cost is the mean of its measured total cost on the OTHER events of
   the cohort (leave-one-event-out); budget = tier fraction x the estimated full-suite cost; real cost reported
   against the event's actual labelled cost.
Run from repo root:  PYTHONPATH=src python scripts/revision_extra.py
"""
from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
import numpy as np
from cart.metrics.evaluate import _build_payloads, _run_metrics
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S
from cart.selectors.cost_model import ORACLE_COST_EST
from cart.selectors import proposed as P

ROOT = Path(__file__).resolve().parents[1]
BASE = ["cheapest_first", "diversity_only", "proposed", "decomposed"]


def _norm(d):
    lo, hi = min(d.values()), max(d.values())
    return {k: (v - lo) / (hi - lo) if hi > lo else 0.0 for k, v in d.items()}


def make_variant(kind):
    def sel(ctx, event_id, budget_s, *, seed=0, **_):
        eps, _t = P._config()
        comps = {t: P._components(ctx, event_id, t, eps) for t in ctx.candidate_test_ids()}
        nc = _norm({t: c.cbs for t, c in comps.items()})
        ni = _norm({t: c.impact_prior for t, c in comps.items()})
        no = _norm({t: c.oracle_confidence for t, c in comps.items()})
        ncost = _norm({t: 1.0 / max(c.cost, 1e-9) for t, c in comps.items()})
        counts, order, rem = {}, [], set(comps)
        while rem:
            def key(t):
                nv = P._novelty(P._combo(ctx, t), counts)
                if kind == "additive":
                    return (nc[t] + ni[t] + no[t] + ncost[t] + nv, t)
                if kind == "lex_severity_first":
                    return (round(ni[t], 6), nv, -comps[t].cost, t)
                if kind == "lex_diversity_first":
                    return (nv, -comps[t].cost, round(ni[t], 6), t)
            b = max(rem, key=key); order.append(b); rem.discard(b)
            counts[P._combo(ctx, b)] = counts.get(P._combo(ctx, b), 0) + 1
        return order
    return sel


def main():
    out = {}
    for data_dir, label in [("data", "primary_9"), ("data_scaleup", "scaleup_19")]:
        pay = _build_payloads(ROOT / data_dir, None, "all")
        variants = {k: make_variant(k) for k in ("additive", "lex_severity_first", "lex_diversity_first")}
        # B + A: AUC per event for baselines and variants
        auc = {}
        for p in pay:
            row = {}
            for n in BASE:
                em, _ = _run_metrics(S[n], p["ctx"], p["event_id"], p["cost"], p["detects"]); row[n] = em.auc_detection_vs_budget
            for n, f in variants.items():
                em, _ = _run_metrics(f, p["ctx"], p["event_id"], p["cost"], p["detects"]); row[n] = em.auc_detection_vs_budget
            row["_frac"] = sum(p["detects"].values()) / len(p["detects"])
            auc[p["event_id"]] = row
        names = BASE + list(variants)
        res = {"n_events": len(pay), "mean_auc": {n: float(np.mean([auc[e][n] for e in auc])) for n in names}}
        strata = {"none(0)": lambda f: f == 0, "rare(0-0.10]": lambda f: 0 < f <= 0.10,
                  "intermediate(0.10-0.48)": lambda f: 0.10 < f < 0.48, "common(>=0.48)": lambda f: f >= 0.48}
        res["by_detectability"] = {}
        for sname, fn in strata.items():
            ev = [e for e in auc if fn(auc[e]["_frac"])]
            res["by_detectability"][sname] = {"n_events": len(ev), **({n: float(np.mean([auc[e][n] for e in ev])) for n in names} if ev else {})}
        res["per_event_auc"] = auc
        # C: deployable cost estimator
        tot = {}
        for p in pay:
            for t, c in p["cost"].items(): tot.setdefault(t, {})[p["event_id"]] = c
        C = {}
        for tier, frac in (("pr", 0.05), ("nightly", 0.50)):
            per = {n: [] for n in ("cheapest_first", "diversity_only", "proposed", "decomposed", "random")}
            for p in pay:
                est = {t: float(np.mean([c for e, c in tot[t].items() if e != p["event_id"]])) for t in p["cost"]}
                bc = dict(p["ctx"].baseline_costs)
                for t, c in est.items():
                    bc[(p["event_id"], t)] = max(c - ORACLE_COST_EST.get(p["ctx"].test_meta(t).oracle_type, 0.05), 1e-9)
                ctx = replace(p["ctx"], baseline_costs=bc)
                budget = frac * sum(est.values()); full = sum(p["cost"].values())
                for n in per:
                    seeds = range(20) if n == "random" else [0]
                    rs = []
                    for s in seeds:
                        ch = [t for t in S[n](ctx, p["event_id"], budget, seed=s) if t in p["cost"]]
                        rs.append((any(p["detects"].get(t, False) for t in ch), sum(p["cost"][t] for t in ch) / full, len(ch)))
                    per[n].append(tuple(np.mean(rs, axis=0)))
            C[tier] = {n: dict(detected=float(np.mean([x[0] for x in v])), real_cost_fraction=float(np.mean([x[1] for x in v])),
                               mean_tests=float(np.mean([x[2] for x in v]))) for n, v in per.items()}
        res["deployable_cost_estimator"] = C
        out[label] = res
    (ROOT / "results" / "revision_extra.json").write_text(json.dumps(out, indent=1))
    print("wrote results/revision_extra.json")


if __name__ == "__main__":
    main()
