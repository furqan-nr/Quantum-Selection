#!/usr/bin/env python3
"""forward_selector_eval.py - evaluate the selectors on one forward-regression event (case study, never pooled).

Reads results/forward_units/<event>.json written by scripts/forward_probe_units.py and applies DETECTION RULES
declared here, before any result is looked at:
  contract_metadata event : a unit detects iff both builds ran and initial_layout.get_registers() differs.
  performance event       : a unit detects iff median(candidate time) / median(baseline time) >= 1.5
                            AND the median difference is >= 0.010 s.
  Clock: the first run used CPU process time, which has a 15.6 ms resolution on Windows and produced
  0.000 s vs 0.016 s artefacts. The amended rule (same thresholds, instrument only) uses the high-resolution
  wall clock (--clock wall, results of the re-run); the CPU-clock result is kept as a documented failed measurement.
Cost of a unit (model scale, same for ranking and for scoring) = median baseline CPU time + the pre-declared
constant oracle-cost estimate of the unit's oracle tier. Both quantities exclude measured oracle time, so this
evaluates ORDERING only (it does not test the cost-model mismatch reported for the mutation cohorts).
History is empty: the forward events pre-date every mutation event, so no prior outcome may be used.
Budgets (--budget-basis, default "pre"): a tier budget is the tier fraction of the PRE-change suite cost
(baseline times + oracle estimates), which is what a CI system knows before the change; the selected set is
then charged at its POST-change cost. "post" (fraction of the post-change suite cost) is kept for comparison.
Reported: detected, real cost / nominal budget, real cost / post-change suite cost, tests selected.

Run (repo root, PYTHONPATH=src):  python scripts/forward_selector_eval.py --event <event_id>
Defaults reproduce the reported results: with only --event, the input is the reported (re-run) file listed in
REPORTED_INPUT below and the clock is "wall". The old v1 CPU-clock input is only used if requested explicitly
(--in-json results/forward_units/<event>.json --clock cpu).
Writes <input stem>_selectors.json next to the input file (e.g. results/forward_units/<event>_v2_selectors.json);
NOTE this overwrites the committed file of that name, so run on a fresh clone or compare with `git diff`.
"""
from __future__ import annotations
import argparse, json, statistics, sys
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from cart.metrics.curves import event_metrics
from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import ORACLE_COST_EST
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S

RATIO, ABS_DIFF = 1.5, 0.010
CLOCK = "wall_times_s"
# Inputs behind the reported forward-event results (wall-clock re-runs). Used when --in-json is not given.
REPORTED_INPUT = {
    "fwd-applylayout-registers-14904": "fwd-applylayout-registers-14904_v2.json",
    "hist-vf2postlayout-noop": "hist-vf2postlayout-noop_v2_corrected.json",
}


def detect(kind: str, rec: dict) -> bool | None:
    b, c = rec["baseline"], rec["candidate"]
    if b.get("status") != "ok" or c.get("status") != "ok":
        return None
    if kind == "contract_metadata":
        return b.get("registers") != c.get("registers")
    mb, mc = statistics.median(b[CLOCK]), statistics.median(c[CLOCK])
    return bool(mc / max(mb, 1e-9) >= RATIO and (mc - mb) >= ABS_DIFF)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("--event", required=True)
    p.add_argument("--in-json", default=None); p.add_argument("--data-dir", default=str(ROOT / "data_scaleup"))
    p.add_argument("--budget-basis", choices=["pre", "post"], default="pre")
    p.add_argument("--clock", choices=["cpu", "wall", "calibrated"], default="wall")
    a = p.parse_args(argv)
    global CLOCK
    CLOCK = {"cpu": "cpu_times_s", "wall": "wall_times_s", "calibrated": "cal_times_s"}[a.clock]
    src = (Path(a.in_json) if a.in_json
           else ROOT / "results" / "forward_units" / REPORTED_INPUT.get(a.event, f"{a.event}.json"))
    print(f"input: {src}  clock: {a.clock}")
    raw = json.loads(src.read_text())
    ctx0 = SelectionContext.load(a.data_dir, events_path=ROOT / "data" / "events" / "events.json")
    ev = ctx0.events[a.event]; kind = ev.fault_type.value
    recs = raw["records"]
    usable = {t: r for t, r in recs.items() if detect(kind, r) is not None and t in ctx0.units}
    skipped = sorted(set(recs) - set(usable))
    detects = {t: detect(kind, r) for t, r in usable.items()}
    base_med = {t: statistics.median(r["baseline"][CLOCK]) for t, r in usable.items()}
    cand_med = {t: statistics.median(r["candidate"][CLOCK]) for t, r in usable.items()}
    orc = {t: ORACLE_COST_EST.get(ctx0.units[t].oracle_type, 0.05) for t in usable}
    cost = {t: cand_med[t] + orc[t] for t in usable}
    bc = {(a.event, t): base_med[t] for t in usable}
    ctx = replace(ctx0, units={t: ctx0.units[t] for t in usable}, baseline_costs=bc, history=[])
    full = sum(cost.values())
    pre_full = sum(base_med[t] + orc[t] for t in usable)
    basis_total = pre_full if a.budget_basis == "pre" else full
    res = {"event_id": a.event, "fault_type": kind, "n_units": len(usable), "n_skipped_units": len(skipped), "skipped": skipped,
           "n_detecting_units": int(sum(detects.values())), "fraction_detecting": float(np.mean(list(detects.values()))),
           "full_suite_cost_s": full, "pre_change_suite_cost_s": pre_full, "budget_basis": a.budget_basis, "rule": {"ratio": RATIO, "abs_diff_s": ABS_DIFF} if kind == "performance" else "registers differ",
           "selectors": {}}
    for n, sel in S.items():
        seeds = range(20) if n == "random" else [0]
        rows = []
        for s in seeds:
            rk = [t for t in sel(ctx, a.event, float("inf"), seed=s) if t in cost]
            em = event_metrics(rk, cost, detects)
            first = next((i + 1 for i, t in enumerate(rk) if detects.get(t)), None)
            fin = {}
            for tier, fr in (("pr", 0.05), ("nightly", 0.50)):
                B = fr * basis_total
                ch = [t for t in sel(ctx, a.event, B, seed=s) if t in cost]
                spent = sum(cost[t] for t in ch)
                fin[tier] = (any(detects.get(t) for t in ch), spent / full, len(ch), spent / B)
            rows.append((em.auc_detection_vs_budget, em.normalized_ttfr, first if first else len(rk) + 1, fin))
        res["selectors"][n] = dict(
            auc=float(np.mean([r[0] for r in rows])), normalized_ttfr=float(np.mean([r[1] for r in rows])),
            tests_to_first_detection=float(np.mean([r[2] for r in rows])),
            pr=dict(detected=float(np.mean([r[3]["pr"][0] for r in rows])), real_cost_fraction=float(np.mean([r[3]["pr"][1] for r in rows])), tests=float(np.mean([r[3]["pr"][2] for r in rows])), cost_over_budget=float(np.mean([r[3]["pr"][3] for r in rows]))),
            nightly=dict(detected=float(np.mean([r[3]["nightly"][0] for r in rows])), real_cost_fraction=float(np.mean([r[3]["nightly"][1] for r in rows])), tests=float(np.mean([r[3]["nightly"][2] for r in rows])), cost_over_budget=float(np.mean([r[3]["nightly"][3] for r in rows]))))
    out = src.with_name(src.stem + ("_selectors.json" if a.budget_basis == "pre" else "_selectors_postbudget.json")); out.write_text(json.dumps(res, indent=1))
    print(f"{a.event} ({kind}): {res['n_detecting_units']}/{res['n_units']} units detect; skipped {len(skipped)}")
    print(f"{'selector':16s} {'AUC':>6s} {'tests->1st':>10s} {'pr det':>6s} {'pr cost/B':>9s} {'ni det':>6s} {'ni cost/B':>9s}")
    for n, r in res["selectors"].items():
        print(f"{n:16s} {r['auc']:6.3f} {r['tests_to_first_detection']:10.1f} {r['pr']['detected']:6.2f} {r['pr']['cost_over_budget']:9.2f} {r['nightly']['detected']:6.2f} {r['nightly']['cost_over_budget']:9.2f}")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
