#!/usr/bin/env python3
"""Build the EMSE scale-up's 19-event mutation-cohort ledger (Phase B1 —
PAPER2_EMSE_SCALEUP_PLAN.md).

Writes data_scaleup/events/events.json and events.csv from
cart.events.mutations_scaleup.scaleup_cohort_operators() (the 9 original operators, imported not
redefined, plus the 10 new ones pre-registered in Phase A). Does NOT touch data/events/ — this is a
parallel ledger for the parallel data_scaleup/ root, exactly like the plan requires.

This script reads no ground-truth label; it only serializes already-frozen operator metadata
(descriptions, target stages) into the Event schema. Running it is safe at any point after Phase A's
pre-registration commit, including before Phase B's Kaggle run.

Usage:  python scripts/build_scaleup_events.py
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cart.events.mutations_scaleup import scaleup_cohort_operators, MUTATION_OPERATORS_SCALEUP
from cart.events.schema import Event, FaultSource, TrainOrTest

OUT_DIR = ROOT / "data_scaleup" / "events"

# Same anchor SHA the original 9 mutation events use (baseline_sha == candidate_sha for every
# mutation event: the "candidate" is the operator applied in-process to the same installed Qiskit
# build, not a from-source build at a different commit — see mutations.py's module docstring).
ANCHOR_SHA = "5a1cf3159aedad954767956d6a5c81a06d043d71"
EVENT_ENVIRONMENT_ID = "smoke-2_4_2"
# The date this scale-up cohort was pre-registered (matches PREREGISTRATION_PHASE_A.md), not a real
# commit date — same convention the original 9 mutation events already use (their event_date is the
# date the mutation corpus was frozen, not a historical commit timestamp).
EVENT_DATE = "2026-08-13"


def _event_id(family: str) -> str:
    # "mut2-" prefix (not "mut-") keeps these visually and programmatically distinct from the
    # primary ledger's 9 "mut-*" rows, even though they live in a different file entirely.
    return f"mut2-{family.replace('_', '-')}-01"


def build_events() -> list[Event]:
    cohort = scaleup_cohort_operators()
    events = []
    for family, op in sorted(cohort.items()):
        eid = _event_id(family)
        events.append(Event(
            event_id=eid,
            baseline_sha=ANCHOR_SHA,
            candidate_sha=ANCHOR_SHA,
            fault_id=f"mut2-{family}-01",
            fault_source=FaultSource.mutation,
            fault_type=op.fault_type,
            event_environment_id=EVENT_ENVIRONMENT_ID,
            split_group_id=f"{ANCHOR_SHA[:12]}+{family}",
            event_date=EVENT_DATE,
            train_or_test=TrainOrTest.test,
            change_metadata=op.change_metadata(),
            mutation_family=family,
            mutation_params={},
            notes=f"EMSE scale-up (PAPER2_EMSE_SCALEUP_PLAN.md Phase A/B2): {op.description}",
            event_kind="controlled_mutation",
            pair_orientation="forward",
            evaluation_cohort="mutation",
            change_metadata_sha="",
        ))
    return events


def write_json(events: list[Event]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "events.json"
    payload = {
        "schema": "event_table/v1",
        "n_events": len(events),
        "events": [e.to_dict() for e in events],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def write_csv(events: list[Event]) -> Path:
    """Matches the primary events.csv's column set exactly, so the same human-readable conventions
    apply. reproducibility_status is deliberately "pending_calibration" (NOT "verified") for every
    row here: Phase A verified these operators are structurally live, safe, and semantics-preserving
    (see mutations_scaleup.py's docstring), but no ground-truth label exists yet — that only happens
    once Phase B's Kaggle run completes. Do not change this status by hand; it should flip only when
    Phase B's actual labeling output is retrieved and checked."""
    path = OUT_DIR / "events.csv"
    header = ["event_id", "fault_id", "source", "event_kind", "evaluation_cohort", "pair_orientation",
              "fault_type", "baseline_sha", "candidate_sha", "change_metadata_sha", "evidence",
              "event_date", "split_group_id", "event_environment_id", "reproducibility_status",
              "reproduction_command", "expected_observable_signal", "notes"]
    repro_cmd = ("python -m cart.cli ground-truth --out-root data_scaleup "
                "--events data_scaleup/events/events.json --unit-limit 116 --cost-repeats 5")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for e in events:
            op = MUTATION_OPERATORS_SCALEUP.get(e.mutation_family)
            expected_signal = op.description if op else "(original 9 operator; see mutations.py)"
            w.writerow([
                e.event_id, e.fault_id, e.fault_source.value, e.event_kind, e.evaluation_cohort,
                e.pair_orientation, e.fault_type.value, e.baseline_sha, e.candidate_sha,
                e.change_metadata_sha, f"controlled mutation operator {e.mutation_family}",
                e.event_date, e.split_group_id, e.event_environment_id, "pending_calibration",
                repro_cmd, expected_signal, e.notes,
            ])
    return path


def main() -> int:
    events = build_events()
    assert len(events) == 19, f"expected 19 scale-up cohort events, got {len(events)}"
    json_path = write_json(events)
    csv_path = write_csv(events)

    # Internal consistency check (both files were written from the same in-memory list, so this is
    # a sanity check on the writers themselves, not an independent cross-check like
    # scripts/validate_ledger.py does for the primary ledger).
    json_ids = {e["event_id"] for e in json.loads(json_path.read_text())["events"]}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        csv_ids = {row["event_id"] for row in csv.DictReader(fh)}
    assert json_ids == csv_ids, f"CSV/JSON id mismatch: {json_ids ^ csv_ids}"

    print(f"wrote {json_path} ({len(events)} events)")
    print(f"wrote {csv_path}")
    print(f"event_ids: {sorted(json_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
