# Paper 2 reproduction package

Reproduces the computational results reported in "A Leakage-Safe, Cost-Aware Regression-Testing
Methodology for the Quantum Transpiler." Code, data, configs, environment recipes, and scripts
only — no manuscript, figures, cover letter, or write-up planning material.

## Contents

- `src/cart/` — the prototype (CLI + manifest, events, oracles, selectors, metrics, validity gates).
- `configs/` — frozen, pre-declared configuration: `budgets.yaml`, `corpus_costhet.yaml`
  (`frozen: true`), `thresholds.yaml`, `stage_map.yaml`, `cutoff.yaml`, `seeds.yaml`.
- `data/`
  - `events/` — the change-event ledger (`events.csv`/`events.json`) with exact candidate/baseline
    commit SHAs, plus audit and provenance notes.
  - `manifest_static/`, `manifest_costhet/` — static test-unit manifests.
  - `profile_baseline/` — calibrated per-unit cost profiles (`profiles.json`, `hardware.json`).
  - `raw/` — write-once raw oracle evidence per (event, test) pair.
  - `derived/labels.json` — labels regenerated from raw evidence.
- `data_scaleup/` — a second, independently frozen data root (same layout as `data/`) for the n=19
  scale-up validation: 9 primary mutation events plus 10 new, pre-registered operators, calibrated
  on a separate Kaggle session before any label was read. Never mixed with `data/`; the primary
  frozen result is untouched by it.
- `environment/` — two-layer environment recipes: the harness lockfile (`requirements.lock`) and
  per-event Qiskit build lockfiles (`events/*.lock`) for from-source builds of the historical and
  forward events.
- `results/` — the frozen, current evaluation outputs the paper reports: `evaluation_costhet_frozen.json`,
  `analyze-costhet-frozen.json`, `robustness_leave2out.json`, `B3_report_costhet.md`, the two
  forward-event verification result JSONs, and the scale-up's own `evaluation_scaleup_frozen.json`,
  `analyze-scaleup-frozen.json`, `scaleup_summary.json`.
- `scripts/` — verification and analysis tooling, including `build_scaleup_events.py` and
  `scaleup_summary.py` for the scale-up validation.
- `tests/` — automated test suite, including `test_decomposed_selector.py` and
  `test_scaleup_operators.py`.
- `METHODOLOGY.md` — the research specification (component definitions, anti-leakage rules,
  validity gates, claim-scope rule).
- `KAGGLE_CALIBRATION.md`, `kaggle_calib.ipynb`, `kaggle_bundle.zip` — how the cost calibration was
  run on Kaggle, and how to redo it on a free-tier machine. `kaggle_calib_scaleup.ipynb` /
  `kaggle_bundle_scaleup.zip` are the equivalent for the scale-up's own, separate calibration session.
- `CORPUS_DESIGN_B1.md` — design rationale for the cost-heterogeneous corpus.
- `FORWARD_EVENTS_B2.md`, `FORWARD_COUNT_DECISION.md`, `BISECTION_AUDIT.md`,
  `FWD_15024_RETRACE.md`, `TRIGGER_15024_FROM_FIXTEST.md`, `RISK_SCORE_INDEPENDENCE.md` —
  forward-event verification and design-independence process notes.
- `PREREGISTRATION_PHASE_A.md` — pre-registration evidence (SHA-256 file manifest, timestamped before
  any scale-up label was read) for the `decomposed` selector's design and the 19-event mutation cohort.
- `pyproject.toml`, `LICENSE`.

## Install

```bash
python -m pip install -e .          # Python 3.11+; or set PYTHONPATH=src
```

Harness dependencies are pinned in `environment/requirements.lock`.

## 1. Reproduce the RQ2/RQ3 headline (mutation cohort, no Rust needed)

The corpus and labels are already committed (`data/raw/`, `data/derived/labels.json`), so the
comparison can be re-run directly against them:

```bash
python -m cart.cli evaluate --split all --random-seeds 20
python -m cart.cli analyze --split all
python scripts/plot_detection_curve.py
python scripts/robustness_leave2out.py
```

Expected: mean detection-vs-budget AUC diversity_only 0.874, cheapest/history/change-stage 0.840,
random 0.821, proposed (`risk_score`) 0.721 (Cliff's delta vs diversity_only = -0.64, large). Exact
frozen numbers are in `results/evaluation_costhet_frozen.json` and `results/analyze-costhet-frozen.json`.

## 2. Reproduce the n=19 scale-up validation (independently pre-registered)

A second, independently pre-registered evaluation tests a `decomposed` selector (diversity first,
cost second, severity only as a tie-break) on an expanded 19-event mutation cohort: the original 9
events plus 10 new, pre-registered operators (`src/cart/events/mutations_scaleup.py`). Its corpus and
budget were calibrated and frozen on a separate Kaggle session, from cost alone, before any label was
read — see `PREREGISTRATION_PHASE_A.md` for the pre-registration evidence and
`configs/corpus_costhet_scaleup.yaml` / `configs/budgets_scaleup.yaml` for the frozen design. The
corpus and labels are already committed (`data_scaleup/raw/`, `data_scaleup/derived/`), so the
comparison can be re-run directly against them:

```bash
python -m cart.cli evaluate --data-dir data_scaleup --selectors scaleup --split all --random-seeds 20 --out-results results/evaluation_scaleup_frozen.json
python -m cart.cli analyze --data-dir data_scaleup --split all
python scripts/scaleup_summary.py
```

Expected: mean detection-vs-budget AUC diversity_only 0.8801, decomposed 0.8798 (Cliff's delta vs
diversity_only = -0.08, negligible — parity, not an outright win), cheapest/history/change-stage
0.8496, random 0.8353, proposed (`risk_score`) 0.7678 (delta vs decomposed = +0.568, large). All six
validity gates pass; label reproducibility is 2,204/2,204 (100%). Exact frozen numbers are in
`results/evaluation_scaleup_frozen.json`, `results/analyze-scaleup-frozen.json`, and
`results/scaleup_summary.json`.

Hardware: Intel(R) Xeon(R) CPU @ 2.20GHz, 4 logical CPUs available, single-thread pinned
(`RAYON_NUM_THREADS=1`, `OMP_NUM_THREADS=1`), Python 3.12, Qiskit 2.4.2 — same protocol as the
primary corpus's own calibration. To re-calibrate this cohort from scratch instead of using the
committed data, follow the same pattern as §3 below, pointed at `data_scaleup/`:

```bash
python -m cart.cli manifest --profile costhet --out-data data_scaleup/manifest_static --no-smoke
python -m cart.cli ground-truth --out-root data_scaleup --events data_scaleup/events/events.json --unit-limit 116 --cost-repeats 5
```

See `KAGGLE_CALIBRATION.md` and `kaggle_calib_scaleup.ipynb` / `kaggle_bundle_scaleup.zip` for a
documented, free-tier-reproducible recipe for this second calibration session.

## 3. Re-calibrate the corpus and labels from scratch

```bash
python -m cart.cli manifest --profile costhet
python -m cart.cli ground-truth --unit-limit 116 --cost-repeats 5
# then set frozen budgets in configs/budgets.yaml from the new cost measurements,
# and configs/corpus_costhet.yaml frozen: true, before running evaluate
python -m cart.cli evaluate --split all --random-seeds 20
```

This overwrites `data/raw/`, `data/profile_baseline/`, and `data/derived/` with measurements from
your own hardware. Absolute costs will differ from the paper's; the relative cost ordering should
not. See `KAGGLE_CALIBRATION.md` for a documented, free-tier-reproducible recipe
(`kaggle_calib.ipynb` + `kaggle_bundle.zip`) instead of using your own machine.

## 4. Independently re-verify the six implementation-validity gates

```bash
python3 -c "from cart.gates.validity import run_all_gates; import json; print(json.dumps(run_all_gates(), indent=2))"
python scripts/validate_ledger.py
```

Expected: 5/6 unconditional PASS; `label_reproducibility` at 1,040/1,044 (99.6%). See
`KAGGLE_CALIBRATION.md` ("RESOLVED 2026-08-08") for the two known mutation types behind the four
exceptions and why they are a measurement-noise boundary, not a defect. (This is the primary n=9
corpus's gate result; the scale-up's own gate result — 2,204/2,204, 100% — is reported in §2 above.)

## 5. Reproduce the two verified forward-regression events (needs a Rust toolchain, from-source Qiskit builds)

```bash
python scripts/verify_h4_perf.py          # H4, PR #14120 - performance channel
python scripts/verify_15024_contract.py   # fwd-applylayout-registers-14904, PR #15024 - contract/metadata channel
```

Building the per-event Qiskit revisions from source uses the lockfiles in `environment/events/*.lock`;
see `environment/ENV.md` and `environment/setup/`. Exact `baseline_sha`/`candidate_sha` per event are
in `data/events/events.json`. The remaining scripts (`bisect_regression.py`,
`find_introducing_commit.py`, `verify_16215_forward.py`, `verify_14919_routing.py`,
`verify_n4_global_phase.py`, `contract_differ_sweep.py`, `add_forward_event.py`,
`repro_fixedseed_nondeterminism.py`, `retro_detect_release.py`, `report_b3.py`) support the
forward-event provenance trail documented in `FORWARD_EVENTS_B2.md`, `BISECTION_AUDIT.md`, and
`FWD_15024_RETRACE.md`.

## 6. Run the automated test suite

```bash
python -m pytest -q
```

Expected: 80 passed, 1 known unrelated failure (`test_targeted`, a pre-existing circuit-width
assertion, not connected to any reported result). This count includes `test_decomposed_selector.py`
and `test_scaleup_operators.py` for the scale-up validation.

## Notes

- `data/raw/` is write-once; `data/derived/labels.json` regenerates from it. Never hand-edit either.
- `configs/corpus_costhet.yaml` and `configs/budgets.yaml` are frozen (`version: 1`, `frozen: true`):
  budgets were set from measured cost alone, before any label was read. Do not re-tune them against
  these results — see `METHODOLOGY.md` §5.4 and `RISK_SCORE_INDEPENDENCE.md`.
- `configs/corpus_costhet_scaleup.yaml` and `configs/budgets_scaleup.yaml` are the scale-up's own,
  independently frozen equivalents (`data_scaleup/`, not `data/`). `decomposed.py` was not modified
  after its result was seen, per the pre-registration in `PREREGISTRATION_PHASE_A.md`.
- This package intentionally excludes the manuscript, figures, cover letter, and write-up planning
  documents. It contains only what is needed to reproduce the computational results.
