#!/usr/bin/env python3
"""Phase C labeling driver (PREREGISTRATION_PHASE_C.md, section "Labeling protocol"). DO NOT RUN before the
pre-registration has been externally timestamped.

It runs the UNCHANGED labeling engine (cart.labels.ground_truth.run_event_test / run_ground_truth, same oracles,
thresholds, cost repeats and write-once raw artifacts as the scale-up) and only adds:
  1. operator lookup across the primary, scale-up and Phase C registries (the engine's lookup function is patched at
     run time, not edited);
  2. a guard that the running Qiskit version equals the cohort's `qiskit_required` (C1 = 2.4.2, C2 = 2.2.3) and that
     RAYON_NUM_THREADS = OMP_NUM_THREADS = 1 (set here before qiskit is imported);
  3. a resumable CHUNK mode for machines that cannot keep one process alive for hours: each call labels the given
     (event, unit) slice, skipping pairs whose write-once raw artifact already exists, and reuses the per-unit baseline
     cost already persisted for that unit by an earlier chunk (the engine measures it once per unit and reuses it across
     events in a single run; chunk mode reproduces that by reading it back); followed by ASSEMBLE, which rebuilds
     derived/labels.json and profile_baseline/profiles.json from the raw artifacts in the engine's own order and format.

Usage
  full run (Kaggle / a workstation; identical to `cart.cli ground-truth`):
    python scripts/run_phase_c_ground_truth.py --cohort C1 --out-root data_phase_c1 --unit-limit 116 --cost-repeats 5
  chunked:
    python scripts/run_phase_c_ground_truth.py --cohort C1 --out-root data_phase_c1 --chunk --units 0:20 [--event-ids ...]
    ... repeat until done ...
    python scripts/run_phase_c_ground_truth.py --cohort C1 --out-root data_phase_c1 --assemble
For C2 use the Qiskit 2.2.3 environment (environment/phase_c/README.md).
"""
from __future__ import annotations

import os

for _k, _v in {"RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "QISKIT_IN_PARALLEL": "TRUE"}.items():
    os.environ.setdefault(_k, _v)

import argparse   # noqa: E402
import hashlib    # noqa: E402
import json       # noqa: E402
import sys        # noqa: E402
import time       # noqa: E402
from dataclasses import asdict  # noqa: E402
from pathlib import Path        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import qiskit                                     # noqa: E402
import cart.labels.ground_truth as GT             # noqa: E402
from cart.events.mutations_phase_c import get_operator_any   # noqa: E402
from cart.events.table import load_events         # noqa: E402
from cart.manifest.static_manifest import units_for          # noqa: E402
from cart.oracles.quality import QualityThresholds           # noqa: E402

GT._get_operator_any_registry = get_operator_any  # run-time patch: Phase C families resolvable by the engine


def _guard(events_path: Path) -> None:
    req = json.loads(events_path.read_text()).get("qiskit_required")
    if req and qiskit.__version__ != req:
        raise SystemExit(f"Qiskit {qiskit.__version__} running but this ledger requires {req}")
    for k in ("RAYON_NUM_THREADS", "OMP_NUM_THREADS"):
        if os.environ.get(k) != "1":
            raise SystemExit(f"{k} must be 1 (single-thread cost protocol)")


def _seed_cost_cache(out_root: Path, units) -> dict:
    cache = {}
    keys = ("cpu_time_s", "cost_median_s", "cost_min_s", "cost_max_s", "cost_iqr_s", "cost_repeats", "cost_warmup")
    for u in units:
        for p in sorted((out_root / "raw").glob(f"*/{u.test_id}/result.json")):
            bp = json.loads(p.read_text())["baseline_profile"]
            cache[u.test_id] = {k: bp[k] for k in keys}
            break
    return cache


def chunk(events, units, out_root: Path, out_root_arg: str, cost_repeats: int) -> None:
    th = QualityThresholds.load()
    cache = _seed_cost_cache(out_root, units)
    for ev in events:
        for u in units:
            if (out_root / "raw" / ev.event_id / u.test_id / "result.json").exists():
                continue
            t0 = time.time()
            GT.run_event_test(ev, u, Path(out_root_arg), thresholds=th, cost_repeats=cost_repeats, cost_cache=cache)
            print(f"{ev.event_id} {u.test_id} {time.time() - t0:.1f}s", flush=True)


def assemble(events, units, out_root: Path, out_root_arg: str) -> None:
    fields = [f for f in GT.LabelRecord.__dataclass_fields__ if f not in ("raw_artifact", "raw_sha256")]
    records, profiles, missing = [], [], []
    for ev in events:
        for u in units:
            rel = Path(out_root_arg) / "raw" / ev.event_id / u.test_id / "result.json"
            p = out_root / "raw" / ev.event_id / u.test_id / "result.json"
            if not p.exists():
                missing.append((ev.event_id, u.test_id))
                continue
            text = p.read_text()
            persisted = json.loads(text)
            records.append(GT.LabelRecord(raw_artifact=str(rel), raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                          **{k: persisted.get(k) for k in fields}))
            profiles.append({"event_id": ev.event_id, "baseline_sha": ev.baseline_sha, "test_id": u.test_id,
                             "event_environment_id": ev.event_environment_id, **persisted["baseline_profile"]})
    if missing:
        raise SystemExit(f"{len(missing)} (event, unit) pairs not labelled yet, e.g. {missing[:3]}")
    (out_root / "derived").mkdir(parents=True, exist_ok=True)
    (out_root / "derived" / "labels.json").write_text(json.dumps(
        {"schema": "labels/v1", "n": len(records), "labels": [asdict(r) for r in records]}, indent=2))
    (out_root / "profile_baseline").mkdir(parents=True, exist_ok=True)
    (out_root / "profile_baseline" / "profiles.json").write_text(json.dumps(
        {"schema": "test_profile_baseline/v1", "key": ["event_id", "baseline_sha", "test_id", "event_environment_id"],
         "n": len(profiles), "profiles": profiles}, indent=2))
    print(f"assembled {len(records)} records")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", required=True, choices=["C1", "C2"])
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--events", default=None)
    ap.add_argument("--unit-limit", type=int, default=116)
    ap.add_argument("--cost-repeats", type=int, default=5)
    ap.add_argument("--chunk", action="store_true")
    ap.add_argument("--units", default=None, help="lo:hi slice of the manifest (chunk mode)")
    ap.add_argument("--event-ids", default=None, help="comma-separated subset (chunk mode)")
    ap.add_argument("--assemble", action="store_true")
    a = ap.parse_args()
    out_root = Path(a.out_root) if Path(a.out_root).is_absolute() else ROOT / a.out_root
    events_path = Path(a.events) if a.events else out_root / "events" / "events.json"
    _guard(events_path)
    events = load_events(events_path)
    units = units_for(out_root)[: a.unit_limit]
    assert len(units) == 116, f"expected the 116-unit corpus, got {len(units)}"
    if a.assemble:
        assemble(events, units, out_root, a.out_root)
        return 0
    if a.chunk:
        lo, hi = (int(x) for x in a.units.split(":")) if a.units else (0, len(units))
        evs = [e for e in events if not a.event_ids or e.event_id in a.event_ids.split(",")]
        chunk(evs, units[lo:hi], out_root, a.out_root, a.cost_repeats)
        return 0
    s = GT.run_ground_truth(events, units, a.out_root, unit_limit=a.unit_limit, cost_repeats=a.cost_repeats)
    print(f"records: {s['n_records']} | label_counts: {s['label_counts']} | skipped: {s['n_events_skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
