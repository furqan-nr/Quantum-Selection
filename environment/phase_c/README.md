# Phase C environments (PREREGISTRATION_PHASE_C.md)

Two labeling environments, one per cohort. Both run the same `cart` source tree (PYTHONPATH=src); nothing is built
from source.

| Cohort | Ledger | Qiskit | Recipe |
|---|---|---|---|
| C1 | `data_phase_c1/events/events.json` | 2.4.2 | the project's existing environment (`environment/requirements.lock`), or `pip install qiskit==2.4.2 numpy scipy pyyaml` |
| C2 | `data_phase_c2/events/events.json` | 2.2.3 | `requirements-qiskit-2.2.3.in` (pinned result: `requirements-qiskit-2.2.3.lock.txt`) |

The labeling driver refuses to run if the installed Qiskit differs from the ledger's `qiskit_required`, or if
`RAYON_NUM_THREADS` / `OMP_NUM_THREADS` are not 1.

## Qiskit 2.2.3 virtual environment (verified 2026-10-16, Python 3.10, Linux sandbox)

```bash
python3 -m venv /tmp/venv_q223
/tmp/venv_q223/bin/pip install -r environment/phase_c/requirements-qiskit-2.2.3.in   # ~2 min
cd <repo root>
PYTHONPATH=src /tmp/venv_q223/bin/python -c "import cart, qiskit; print(qiskit.__version__)"   # -> 2.2.3
PYTHONPATH=src /tmp/venv_q223/bin/python -m pytest -q tests/test_coast.py tests/test_scaleup_operators.py   # 22 passed
```

Resolved versions (`requirements-qiskit-2.2.3.lock.txt`): qiskit 2.2.3, numpy 2.2.6, scipy 1.15.3, rustworkx 0.18.1,
PyYAML 6.0.3, stevedore 5.8.0, dill 0.4.1. The C1 sandbox environment: qiskit 2.4.2 with the same numpy/scipy/rustworkx.

## Verification evidence (transpilation only; no Phase C label was produced)

`verification/`:
- `firing_sweep_qiskit_2_4_2.jsonl`: every operator x all 116 units, baseline vs mutated transpilation: output
  changed?, quality-rule flag and 2Q/depth deltas, structural validity, CPU time. Summary in
  `operator_verification_summary.json`.
- `firing_sweep_dropped_candidates_qiskit_2_4_2.jsonl`: the dropped candidate `line_wide_dense_layout` (changed 18
  outputs, never crossed the quality thresholds).
- `compat_sweep_qiskit_2_2_3.jsonl`: every operator x all 116 units under Qiskit 2.2.3: terminates without error and
  output changed? (no quality rule, no oracle computed, deliberately).
- `equivalence_checks_qiskit_2_4_2.jsonl`: exact unitary equivalence on 13 five/eight-qubit units and one 12-qubit unit
  (ghz-n12-line-opt1).
- `timing_dry_run.jsonl`: the unchanged labeling engine (`run_event_test`) on two units of an EXISTING scale-up event
  (mut2-seed-drift-01) under both Qiskit versions, output written to /tmp only.

## Labeling time estimate

Measured (timing_dry_run): on this 2-vCPU sandbox a 12-qubit exact check of ghz-n12-line-opt1 took 13.9 s (2.4.2) and
14.6 s (2.2.3) versus 26.0 s in scale-up session B (Kaggle), and the transpilation cost of qft-n127-line-opt1 was 2.03 s
versus 4.30 s, i.e. this sandbox is ~2x faster than the Kaggle sessions (ratio ~0.47-0.53). The full pipeline costs
about 13.6x the unit's transpilation cost when the per-unit cost measurement is included (first event) and about 7.5x
afterwards, plus the oracle.

Per event: oracle ~1220 s (session B mean) and ~7.5 x 63 s transpilation on Kaggle, i.e. ~28 min per event, ~4.7 h per
10-event cohort, ~9.5 h for C1 + C2; on this sandbox ~0.53 x 1220 + 7.5 x 30 ~ 15 min per event, ~2.5 h per cohort,
~5 h for both sequentially (~2.6 h with one process per cohort on the two cores; peak memory of a 12-qubit exact check
is well under 1 GB per process).

Chunk timing (red-team check, scratch copy in /tmp, labels not inspected and deleted): one call labelling the cheap
unit ghz-n5-line-opt1 for all ten C1 events took < 1 s wall time including start-up. From session-B costs at the
sandbox speed ratio (~0.5), one cohort is ~2.4 h of work, i.e. about 27 calls of <= 8 min per cohort (~55 for C1+C2);
the four 12-qubit qft/random_clifford line units need ~4 calls each (three events per call, `--event-ids`).

Practical constraint of this sandbox (earlier note): tool calls were capped at ~3 minutes and background processes do not survive a
call, so a run here must use the chunked mode (`scripts/run_phase_c_ground_truth.py --chunk --units lo:hi`, then
`--assemble`); the most expensive units (random_clifford-n12-line, ~150 s of oracle here) need one call each. The
pre-registered default is therefore a Kaggle CPU session (same class as sessions A and B), one cohort per session.
If labeling runs on a machine of a different speed class, the pre-registered speed rule
(`cart.selectors.coast.speed_factor`, applied by `scripts/phase_c_analysis.py`) rescales the previous-session
estimates and both budget rules by the measured baseline-transpilation speed ratio.
