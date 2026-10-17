# Quantum Selection: reproduction package

Reproduces the computational results of "Oracle Cost, Not the Scoring Function: An Empirical Study of Budgeted Test
Prioritization for the Qiskit Transpiler" (Nasir, Shah, Alam; submitted to the Software Quality
Journal). An earlier version of the study is available as arXiv:2609.35834 ("A Leakage-Safe, Cost-Aware Regression
Testing Methodology for the Quantum Transpiler"). Code, data, configs, environment recipes and scripts only.

**Start with `REPRODUCE.md`**, which maps every table and figure of the manuscript to its source file and command.

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
  scale-up validation: 9 primary mutation events plus 10 new, pre-specified operators, calibrated
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
- `PREREGISTRATION_PHASE_C.md` and `PREREGISTRATION_PHASE_C.sha256` — the pre-registered confirmatory study
  (RQ6 of the manuscript), frozen and pushed in commit `36a5bbb` (2026-10-16) before any Phase C label existed.
  Its labels are in `data_phase_c1/` (Qiskit 2.4.2) and `data_phase_c2/` (Qiskit 2.2.3), its result in
  `results/phase_c_confirmatory.json`, its labeling environment and record in `environment/phase_c/`, and an
  independent re-check in `verification/phase_c_independent_check.md`. The frozen files must not be edited.
- `pyproject.toml`, `LICENSE`.

## Install

```bash
python -m pip install -r environment/requirements.lock   # Python 3.11 or 3.12 required
python -m pip install -e .                               # or set PYTHONPATH=src
```

Harness dependencies are pinned in `environment/requirements.lock` (numpy 2.4.x, which needs Python 3.11 or
newer). The analysis scripts rewrite their own output files in `results/` (and `scripts/plot_sqj_figures.py`
writes into `paper/sqj/`), so run them on a fresh clone or check the effect with `git diff`; see `REPRODUCE.md`.

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
proposed (`risk_score`) 0.721 (Cliff's delta vs diversity_only = -0.64, large). For random ordering,
the frozen evaluation reports 0.821 on the 9 events: the mean AUC over the 20 seeds (0-19) used by
`--random-seeds 20` (the median over those seeds, 0.809, is in `random_multiseed`). The manuscript's
tables instead use the 100-seed mean, 0.832 on the 9 events and 0.850 on the 19 scale-up events,
produced by `python scripts/revision_stats_extra.py` (`results/revision_stats_extra.json`,
`A_random_100_seeds`). Exact frozen numbers are in `results/evaluation_costhet_frozen.json` and
`results/analyze-costhet-frozen.json`. Without `--out-results`, `evaluate` and `analyze` write to new
timestamped folders under `results/` and never touch the frozen files.

## 2. Reproduce the n=19 scale-up validation (separately pre-specified)

A second, separately pre-specified evaluation tests a `decomposed` selector (diversity first,
cost second, severity only as a tie-break) on an expanded 19-event mutation cohort: the original 9
events plus 10 new, pre-specified operators (`src/cart/events/mutations_scaleup.py`). Its corpus and
budget were calibrated and frozen on a separate Kaggle session, from cost alone, before any label was
read — see `PREREGISTRATION_PHASE_A.md` for the pre-registration evidence and
`configs/corpus_costhet_scaleup.yaml` / `configs/budgets_scaleup.yaml` for the frozen design. The
corpus and labels are already committed (`data_scaleup/raw/`, `data_scaleup/derived/`), so the
comparison can be re-run directly against them:

```bash
python -m cart.cli evaluate --data-dir data_scaleup --selectors scaleup --split all --random-seeds 20 --out-results results/rerun_evaluation_scaleup.json
python -m cart.cli analyze --data-dir data_scaleup --split all
python scripts/scaleup_summary.py     # reads the frozen evaluation_scaleup_frozen.json, rewrites results/scaleup_summary.json
```

Compare `results/rerun_evaluation_scaleup.json` with the frozen `results/evaluation_scaleup_frozen.json`
(do not write over the frozen file). Expected: mean detection-vs-budget AUC diversity_only 0.8801, decomposed 0.8798 (Cliff's delta vs
diversity_only = -0.08, negligible — parity, not an outright win), cheapest/history/change-stage
0.8496, random 0.8353 (20-seed mean; the manuscript uses the 100-seed mean, 0.850), proposed (`risk_score`) 0.7678 (delta vs decomposed = +0.568, large). All six
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

## 5b. Reproduce the pre-registered Phase C analysis (RQ6, no transpilation)

```bash
sha256sum -c PREREGISTRATION_PHASE_C.sha256
PYTHONPATH=src python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup --out /tmp/phase_c.json
```

Apart from `runtime_s` and the absolute paths it records, `/tmp/phase_c.json` equals
`results/phase_c_confirmatory.json`. See `REPRODUCE.md` for relabeling and the documented deviation.

## 6. Run the automated test suite

```bash
python -m pytest -q
```

Expected: 81 passed. This count includes `test_decomposed_selector.py` and
`test_scaleup_operators.py` for the scale-up validation.

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

## Finite-budget and schematic scripts (post-hoc)

- `scripts/revision_budgeted.py` -> `results/revision_budgeted.json`: re-runs every selector with a finite budget (frozen model-cost budgets and measured-cost regimes), with exact sign tests, sensitivity and ablation.
- `scripts/revision_extra.py` -> `results/revision_extra.json`: alternative score combiners, detectability strata and a leave-one-event-out cost estimator.
- `scripts/revision_stats_extra.py` -> `results/revision_stats_extra.json`: random ordering over 100 seeds, equivalence (TOST) and Bayesian bootstrap, power simulation, APFDc, and the paired table of the SQJ manuscript.
- `scripts/budgeted_check.py`: independent check of the finite-budget result.
- `scripts/make_schematics.py`: redraws the three schematic figures with matplotlib (no generative AI).

## Post-hoc analyses (not pre-specified)
`PYTHONPATH=src python scripts/revision_reanalysis.py` reads the frozen `data_scaleup/` labels and writes `results/revision_reanalysis.json`: paired Wilcoxon tests with Holm correction, original-9 vs new-10 cohorts, detection fractions, seconds to first detection, and a drop_vf2_post_layout sensitivity check. `scripts/plot_detection_curve_scaleup.py` regenerates the 19-event detection-curve figure.
