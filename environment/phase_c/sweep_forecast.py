#!/usr/bin/env python3
"""Registered SWEEP FORECAST of the Phase C selector outcomes (PREREGISTRATION_PHASE_C.md, Sections 8-9).

Written during the pre-freeze red-team review, BEFORE any Phase C label. It makes explicit what the transpilation-only
sweeps already reveal: Phase C detection sets are deterministic functions of transpiler output, so they can be
predicted from environment/phase_c/verification/firing_sweep_qiskit_2_4_2.jsonl, and the per-unit costs can be
predicted from sessions A and B. Combining the two and running the FROZEN analysis script gives a forecast of every
selector comparison (H1-H4). The forecast is published so that readers can see exactly what was knowable before
labeling; it is the reason H1-H4 are registered as forecast checks rather than confirmatory hypotheses.

Proxy labels (one per event x unit; C2 uses the 2.4.2 quality flags because the 2.2.3 sweep recorded only
termination and output change, and its per-unit output-change sets equal the 2.4.2 ones for all 1160 pairs):
  quality    : detected iff the 2.4.2 sweep's quality-rule flag fired
  functional : detected iff the 2.4.2 sweep found the output structurally invalid
  semantic   : detected iff the output changed AND the unit's predicted oracle tier is exact (coast.effective_oracle_tier)
Proxy costs: per unit, the pooled session A/B means (cpu_time_s + oracle_cost_s) -- i.e. exactly the frozen
previous-session estimate, so the forecast of P1/P2 is uninformative BY CONSTRUCTION and is not reported as a forecast.
Sensitivity: the same forecast with session-A-only and session-B-only costs.

Run from the repo root:  python environment/phase_c/sweep_forecast.py
Writes environment/phase_c/verification/sweep_forecast.json (temporary proxy roots live in a temp dir only).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("phase_c_analysis", ROOT / "scripts" / "phase_c_analysis.py")
PCA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PCA)

from cart.selectors.coast import effective_oracle_tier, session_unit_table   # noqa: E402
from cart.manifest.static_manifest import units_for                         # noqa: E402

SWEEP = ROOT / "environment/phase_c/verification/firing_sweep_qiskit_2_4_2.jsonl"
OUT = ROOT / "environment/phase_c/verification/sweep_forecast.json"


def build_proxy_root(cohort_root: Path, dst: Path, cost_roots: list[str]) -> dict[str, list[str]]:
    shutil.copytree(cohort_root / "events", dst / "events")
    shutil.copytree(cohort_root / "manifest_static", dst / "manifest_static")
    units = {u.test_id: u for u in units_for(cohort_root)}
    tabs = [session_unit_table(ROOT / r) for r in cost_roots]
    cost = {t: {k: sum(tb[t][k] for tb in tabs) / len(tabs) for k in ("cpu_time_s", "oracle_cost_s")} for t in units}
    size = {t: tabs[0][t].get("out_size", 10.0) for t in units}
    sweep = {(r["op"], r["unit"]): r for r in map(json.loads, SWEEP.read_text().splitlines())}
    events = json.loads((cohort_root / "events" / "events.json").read_text())["events"]
    labels, profs, pred = [], [], {}
    for e in events:
        op, ft = e["mutation_family"], e["fault_type"]
        pred[e["event_id"]] = []
        for t, u in units.items():
            s = sweep[(op, t)]
            if ft == "quality":
                d = bool(s["qual"])
            elif ft == "functional":
                d = s["struct_ok"] is False
            else:
                d = bool(s["changed"]) and effective_oracle_tier(u) == "exact"
            if d:
                pred[e["event_id"]].append(t)
            c = cost[t]
            labels.append({"event_id": e["event_id"], "test_id": t, "label": "proxy_detect" if d else "pass",
                           "fault_id_detected": e["fault_id"] if d else None, "cpu_time_s": c["cpu_time_s"],
                           "oracle_cost_s": c["oracle_cost_s"], "total_cost_s": c["cpu_time_s"] + c["oracle_cost_s"]})
            profs.append({"event_id": e["event_id"], "test_id": t, "cpu_time_s": c["cpu_time_s"], "out_size": size[t]})
    (dst / "derived").mkdir(parents=True)
    (dst / "profile_baseline").mkdir(parents=True)
    (dst / "derived" / "labels.json").write_text(json.dumps({"labels": labels}))
    (dst / "profile_baseline" / "profiles.json").write_text(json.dumps({"profiles": profs}))
    return {k: sorted(v) for k, v in pred.items()}


def run(cost_roots: list[str], tmp: Path) -> tuple[dict, dict]:
    tag = "_".join(cost_roots)
    pred, specs = {}, []
    for name, root in (("C1", "data_phase_c1"), ("C2", "data_phase_c2")):
        dst = tmp / f"{name}_{tag}"
        pred.update(build_proxy_root(ROOT / root, dst, cost_roots))
        specs += ["--cohort", f"{name}={dst}"]
    res = PCA.main(specs + ["--out", str(tmp / f"forecast_{tag}.json"), "--forecast", str(tmp / "none.json")])
    return res, pred


def strip(h: dict) -> dict:
    keep = ("statistic", "per_operator", "n_operators", "wins", "losses", "ties", "mean", "p_one_sided",
            "secondary_perm_p_one_sided", "p_holm", "conditions", "supported")
    return {k: h[k] for k in keep if k in h}


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        res, pred = run(["data", "data_scaleup"], tmp)
        sens = {}
        for r in ("data", "data_scaleup"):
            rs, _ = run([r], tmp)
            sens[f"costs_{r}_only"] = {k: strip(v) for k, v in rs["registered_forecast_checks"].items()}
    out = {"schema": "phase_c_sweep_forecast/v1",
           "written_before_any_phase_c_label": True,
           "inputs": {"sweep": str(SWEEP.relative_to(ROOT)), "sweep_sha256": PCA.sha256(SWEEP),
                      "analysis_script_sha256": PCA.sha256(ROOT / "scripts" / "phase_c_analysis.py"),
                      "cost_sessions": ["data", "data_scaleup"]},
           "proxy_label_rule": {"quality": "2.4.2 quality-rule flag", "functional": "2.4.2 structurally invalid",
                                "semantic": "output changed and predicted oracle tier exact",
                                "C2": "2.4.2 flags (2.2.3 output-change sets identical for all 1160 operator x unit pairs)"},
           "predicted_detecting_units": pred,
           "predicted_n_detecting_units": {k: len(v) for k, v in pred.items()},
           "forecast_hypotheses": {k: strip(v) for k, v in res["registered_forecast_checks"].items()},
           "forecast_mechanism_checks": res["mechanism_checks"],
           "forecast_secondary_event_level": res["secondary_event_level"],
           "forecast_per_event_auc": {c: {e: {"auc": r["auc"], "n_detecting_units": r["n_detecting_units"]}
                                          for e, r in v.items()} for c, v in res["per_event"].items()},
           "sensitivity_to_cost_source": sens,
           "note": "P1/P2 are not forecast: proxy costs equal the frozen estimate, so their proxy values are trivially "
                   "perfect. Only the realised costs of the new sessions can test them."}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float))
    print("wrote", OUT, {k: (v["wins"], v["losses"], v["ties"], round(v["p_holm"], 4), v["supported"])
                         for k, v in out["forecast_hypotheses"].items()})


if __name__ == "__main__":
    main()
