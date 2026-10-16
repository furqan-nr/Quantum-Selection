#!/usr/bin/env python3
"""Build the Phase C event ledgers (PREREGISTRATION_PHASE_C.md). Reads no label and runs no transpilation.

  C1: the 10 Phase C operators (cart.events.mutations_phase_c) on Qiskit 2.4.2  -> data_phase_c1/
  C2: the same 10 operators on Qiskit 2.2.3                                    -> data_phase_c2/

For each root it writes events/events.json + events.csv and copies the 116-unit cost-heterogeneous manifest
(manifest_static/manifest_static.json, byte-identical in data/ and data_scaleup/), so that
`scripts/run_phase_c_ground_truth.py --out-root data_phase_c1 ...` labels exactly the same corpus.
Existing ledgers are never overwritten (write-once); pass --force only before the pre-registration timestamp.

Usage:  python scripts/build_phase_c_events.py [--force]
"""
import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cart.events.mutations_phase_c import MUTATION_OPERATORS_PHASE_C, phase_c_metadata  # noqa: E402
from cart.events.schema import Event, FaultSource, TrainOrTest                             # noqa: E402

EVENT_DATE = "2026-10-16"          # pre-registration date (same convention as the scale-up ledger)
COHORTS = {
    "C1": {"root": "data_phase_c1", "prefix": "mutc1", "qiskit": "2.4.2",
           "sha": "5a1cf3159aedad954767956d6a5c81a06d043d71",      # same anchor as the primary/scale-up mutation events
           "env": "phasec-qiskit-2_4_2"},
    "C2": {"root": "data_phase_c2", "prefix": "mutc2", "qiskit": "2.2.3",
           "sha": "pypi:qiskit==2.2.3",                               # PyPI wheel; no from-source build is used
           "env": "phasec-qiskit-2_2_3"},
}
MANIFEST_SRC = ROOT / "data_scaleup" / "manifest_static" / "manifest_static.json"


def build_events(cohort: str) -> list[Event]:
    c = COHORTS[cohort]
    out = []
    for family, op in sorted(MUTATION_OPERATORS_PHASE_C.items()):
        slug = family.replace("_", "-")
        out.append(Event(
            event_id=f"{c['prefix']}-{slug}-01", baseline_sha=c["sha"], candidate_sha=c["sha"],
            fault_id=f"{c['prefix']}-{family}-01", fault_source=FaultSource.mutation, fault_type=op.fault_type,
            event_environment_id=c["env"], split_group_id=f"{c['sha'][:12]}+{family}", event_date=EVENT_DATE,
            train_or_test=TrainOrTest.test, change_metadata=op.change_metadata(), mutation_family=family,
            mutation_params={"qiskit_required": c["qiskit"], **phase_c_metadata()},
            notes=f"Phase C {cohort} (Qiskit {c['qiskit']}): {op.description}",
            event_kind="controlled_mutation", pair_orientation="forward", evaluation_cohort="mutation",
            change_metadata_sha=""))
    return out


def write(cohort: str, force: bool) -> Path:
    c = COHORTS[cohort]
    root = ROOT / c["root"]
    ev_dir = root / "events"
    jp = ev_dir / "events.json"
    if jp.exists() and not force:
        raise SystemExit(f"{jp} exists (write-once); refusing to overwrite")
    events = build_events(cohort)
    assert len(events) == 10
    ev_dir.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps({"schema": "event_table/v1", "n_events": len(events), "cohort": cohort,
                              "qiskit_required": c["qiskit"], "events": [e.to_dict() for e in events]}, indent=2))
    header = ["event_id", "fault_id", "source", "event_kind", "evaluation_cohort", "pair_orientation", "fault_type",
              "baseline_sha", "candidate_sha", "change_metadata_sha", "evidence", "event_date", "split_group_id",
              "event_environment_id", "reproducibility_status", "reproduction_command", "expected_observable_signal", "notes"]
    cmd = (f"python scripts/run_phase_c_ground_truth.py --cohort {cohort} --out-root {c['root']} "
           f"--events {c['root']}/events/events.json --unit-limit 116 --cost-repeats 5")
    with open(ev_dir / "events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for e in events:
            op = MUTATION_OPERATORS_PHASE_C[e.mutation_family]
            w.writerow([e.event_id, e.fault_id, e.fault_source.value, e.event_kind, e.evaluation_cohort, e.pair_orientation,
                        e.fault_type.value, e.baseline_sha, e.candidate_sha, e.change_metadata_sha,
                        f"controlled mutation operator {e.mutation_family}", e.event_date, e.split_group_id,
                        e.event_environment_id, "pending_labeling", cmd, op.description, e.notes])
    man = root / "manifest_static"
    man.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MANIFEST_SRC, man / "manifest_static.json")
    assert hashlib.sha256((man / "manifest_static.json").read_bytes()).hexdigest() == \
        hashlib.sha256((ROOT / "data" / "manifest_static" / "manifest_static.json").read_bytes()).hexdigest()
    return jp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for cohort in COHORTS:
        p = write(cohort, a.force)
        ids = [e["event_id"] for e in json.loads(p.read_text())["events"]]
        print(f"{cohort}: wrote {p} ({len(ids)} events): {ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
