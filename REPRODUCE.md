# Reproducing "Oracle Cost, Not the Scoring Function: An Empirical Study of Budgeted Test Prioritization for the Qiskit Transpiler"

Software Quality Journal submission (collection "Quantum Software Quality"). Repository: https://github.com/furqan-nr/Quantum-Selection (MIT license). An earlier version of the study is arXiv:2609.35834.

## Setup

Python 3.11 or 3.12 is required (the lock pins numpy 2.4.x, which needs Python 3.11 or newer).

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r environment/requirements.lock        # pinned harness (Qiskit 2.4.2, matplotlib for the figures)
pip install -e .                                    # or: export PYTHONPATH=src
python -m pytest -q                                 # expect: 81 passed
```

All analysis scripts read the frozen labels and costs and run without transpilation. Run them from the repository root with `PYTHONPATH=src`. They never modify the frozen inputs (`data/`, `data_scaleup/`, `results/*_frozen.json`), but each one rewrites its own output file in `results/` (for example `scripts/revision_stats_extra.py` rewrites `results/revision_stats_extra.json`, and `scripts/forward_selector_eval.py` rewrites `results/forward_units/<input>_selectors.json`), and `scripts/plot_sqj_figures.py` writes the figures into `paper/sqj/`. Run them on a fresh clone, or check the effect with `git diff`: a faithful re-run leaves the committed JSON files unchanged. `python -m cart.cli evaluate` and `analyze` without `--out-results` write to new timestamped folders under `results/`; never pass a `*_frozen.json` path to `--out-results`.

## Where every table and figure comes from

| Manuscript item | Source file(s) | Command |
|---|---|---|
| Table 3 (corpus, budgets) | `configs/corpus_costhet.yaml`, `configs/budgets.yaml`, `data/profile_baseline/profiles.json` | frozen; see the `frozen_calibration_2026_08_07` block |
| Table 4 (mutation operators) | `src/cart/events/mutations.py`, `src/cart/events/mutations_scaleup.py`, `PREREGISTRATION_PHASE_A.md` | n/a |
| Table 5 (RQ1, 9 events) | `results/evaluation_costhet_frozen.json`; random over 100 seeds: `results/revision_stats_extra.json` | `python -m cart.cli evaluate --split all --random-seeds 20`; `python scripts/revision_stats_extra.py` |
| Table 6 (ablation, combiners, re-ranking with estimated costs) | `results/analyze-costhet-frozen.json`, `results/analyze-scaleup-frozen.json`, `results/revision_costscale.json` | `python -m cart.cli analyze --split all` (add `--data-dir data_scaleup` for 19 events); `python scripts/revision_costscale.py` |
| Table 7 (detectability strata) | `results/revision_extra.json` | `python scripts/revision_extra.py` |
| Table 8 (RQ3, 19 events) | `results/evaluation_scaleup_frozen.json`, `results/revision_stats_extra.json` | `python -m cart.cli evaluate --data-dir data_scaleup --selectors scaleup --split all --random-seeds 20`; `python scripts/revision_stats_extra.py` |
| Table 9 (paired tests) | rows 1-7: `results/revision_stats_extra.json` (`F_paired_family7_random100`); last row: `results/revision_reanalysis.json` (`paired_tests.new10`) | `python scripts/revision_stats_extra.py`; `python scripts/revision_reanalysis.py` |
| Table 10 (frozen budgets in real seconds) | `results/revision_costscale.json` (`s5_frozen_budgets`); earlier percentage-of-suite view: `results/revision_budgeted.json` | `python scripts/revision_costscale.py` |
| Table 11 (forward regressions) | `results/forward_units/fwd-applylayout-registers-14904_v2*.json`, `results/forward_units/hist-vf2postlayout-noop_v2_corrected*.json` | `python scripts/forward_selector_eval.py --event fwd-applylayout-registers-14904` and `--event hist-vf2postlayout-noop` (the defaults select the reported `_v2` / `_v2_corrected` input and the wall clock; add `--budget-basis post` for the `_postbudget` files) |
| Forward regressions under the study's own oracles; event dependence and deduplicated tests | `results/revision_dependence.json` | `python scripts/revision_dependence.py` |
| Equivalence, Bayesian bootstrap, power, APFDc | `results/revision_stats_extra.json` | `python scripts/revision_stats_extra.py` |
| Label counts (oracle tiers, detections, false positives) | `data/derived/labels.json`, `data_scaleup/derived/labels.json` | read the `oracle_strength`, `fault_id_detected`, `label` and `confirmed` fields |
| Figs. 1-3 (Fig. 3 from `results/revision_costscale.json`) | the results files above | `python scripts/plot_sqj_figures.py` |
| Online Resource 1, Tables S1-S6 | the results files above | as above |
| Section 11 / RQ6 (Phase C, pre-registered): Tables 12-14 | `PREREGISTRATION_PHASE_C.md`, `configs/phase_c_cost_model.json`, `data_phase_c1/`, `data_phase_c2/`, `results/phase_c_confirmatory.json` | `python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup --out /tmp/phase_c.json` (see below) |
| Online Resource 1, Phase C section (per-event AUC, operators, estimator accuracy, forecast vs realised, restart sensitivity) | `results/phase_c_confirmatory.json`, `environment/phase_c/verification/sweep_forecast.json`, `verification/phase_c_independent_check.md` | as above |

## Validity gates for the primary (9-event) evaluation

`results/evaluation_costhet_frozen.json` was produced by an earlier code version, before the validity gates were wired into `evaluate`, so it has no `validity_gates` block. It is kept unchanged. Re-running the released code on the committed data,

```bash
python -m cart.cli evaluate --split all --random-seeds 20 --out-results /tmp/eval_primary_rerun.json
```

gives identical AUCs and every other metric (the only differences are the measured selection-overhead times and the `cutoff_date` field, which is now read from `configs/cutoff.yaml` and does not affect `--split all`), and reports the gates as:

| Gate | Result | Detail |
|---|---|---|
| metric_correctness | PASS | caseA=True, caseB=True |
| budget_compliance | PASS | 0 over-budget (event x selector) |
| reproducibility | PASS | 0 non-deterministic rankings |
| leakage_absence | PASS | 0 rankings changed by current-event outcome |
| label_reproducibility | FAIL | 4 label mismatches, 0 missing raw artifacts (1,040/1,044 labels reproduced) |
| oracle_coverage | PASS | 0 records missing oracle_strength/raw_artifact |

The command therefore exits with status 1 (`all gates passed: False`). The four mismatches are the known timing flags: raw artifact `performance_regression` but label `pass` for `mut-insert-redundant-cx-01` / `qft-n5-line-opt1` and `mut-insert-redundant-x-01` / `qaoa_linear-n8-heavy_hex-opt1` and `-opt3`, and raw artifact `pass` but label `performance_regression` for `mut-insert-redundant-x-01` / `ghz-n5-line-opt3`. None of them is a fault detection (`fault_id_detected` is empty for all four), so no detection outcome depends on them; see `KAGGLE_CALIBRATION.md`. The scale-up cohort's frozen evaluation (`results/evaluation_scaleup_frozen.json`) includes its own gate block, with all six gates passing (2,204/2,204 labels).

## Forward regressions (optional; needs from-source Qiskit builds and a Rust toolchain)

The two historical regressions need the last-good and introducing Qiskit builds (commit identifiers are in `data/events/events.json`). Build them with `environment/setup/build_qiskit_event.ps1` (see `environment/setup/SETUP_WINDOWS.md`), then run, for each event:

```bash
python scripts/forward_probe_units.py --event fwd-applylayout-registers-14904 --out results/forward_units/rerun_fwd-applylayout-registers-14904.json --baseline-python <base venv python> --candidate-python <cand venv python>
python scripts/forward_probe_units.py --event hist-vf2postlayout-noop --out results/forward_units/rerun_hist-vf2postlayout-noop.json --baseline-python <base venv python> --candidate-python <cand venv python>
python scripts/forward_selector_eval.py --event fwd-applylayout-registers-14904 --in-json results/forward_units/rerun_fwd-applylayout-registers-14904.json
python scripts/forward_selector_eval.py --event hist-vf2postlayout-noop --in-json results/forward_units/rerun_hist-vf2postlayout-noop.json
```

Use a new `--out` file as above: `forward_probe_units.py` resumes from an existing output file, so pointing it at a committed `_v2.json` would skip every unit. Compare the resulting `rerun_*_selectors.json` with the committed `_v2_selectors.json` / `_v2_corrected_selectors.json`. The evaluation uses the wall clock by default (`--clock wall`): Windows CPU process time has a 15.6 ms resolution. The original CPU-clock result is kept as a documented failed measurement and is only reproduced on request (`--in-json results/forward_units/<event>.json --clock cpu`). The stored `hist-vf2postlayout-noop_v2.json` was recorded with the two build directories swapped. `hist-vf2postlayout-noop_v2_corrected.json` relabels baseline and candidate and documents why in its `label_correction` field. Verification notes for both events: `FORWARD_EVENTS_B2.md`, `FWD_15024_RETRACE.md`, `TRIGGER_15024_FROM_FIXTEST.md`, `BISECTION_AUDIT.md`.

## Re-running the calibration (optional, about one hour on a cloud CPU)

The frozen costs and labels were produced on single-thread-pinned cloud CPUs with `kaggle_calib.ipynb` (primary cohort) and `kaggle_calib_scaleup.ipynb` (scale-up cohort); see `KAGGLE_CALIBRATION.md`. Fresh runs reproduce labels exactly except for timing flags on 1-3 ms units, which do not affect any detection.

## Phase C: pre-registered confirmatory study (RQ6)

The pre-registration `PREREGISTRATION_PHASE_C.md` and the files listed in `PREREGISTRATION_PHASE_C.sha256` were frozen and pushed to the public repository (commit `36a5bbb`, 2026-10-16) before any Phase C label existed. Do not edit them: any change is a deviation under Section 11 of the record.

1. Check the frozen files: `sha256sum -c PREREGISTRATION_PHASE_C.sha256` (all 28 entries must report OK).
2. Re-run the confirmatory analysis on the committed labels, writing to a new file:

   ```bash
   PYTHONPATH=src python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup --out /tmp/phase_c.json
   ```

   Apart from `runtime_s` and the absolute paths it records, the output equals `results/phase_c_confirmatory.json` (the independent check found it byte-identical under two `PYTHONHASHSEED` values). Never point `--out` at the committed file.
3. Relabeling (optional, several hours per cohort): `scripts/run_phase_c_ground_truth.py` with C1 under Qiskit 2.4.2 (the main lock) and C2 under Qiskit 2.2.3 (`environment/phase_c/requirements-qiskit-2.2.3.lock.txt`). The labels in the repository were produced on the machine recorded in `environment/phase_c/labeling_environment.txt`, calling the driver's chunk mode one pair at a time through `environment/phase_c/run_slice.py` (which reads per-unit time predictions from `environment/phase_c/unit_cost_B.json`; adjust the two absolute paths at its top). The deviation during C2 (a sandbox restart after 1,126 of 1,160 pairs) and its sensitivity analysis are in `verification/phase_c_independent_check.md`.
4. The registered sweep forecast can be regenerated with `python environment/phase_c/sweep_forecast.py` (inputs: the transpilation-only sweeps in `environment/phase_c/verification/`). Caution: the script writes to the committed, frozen `environment/phase_c/verification/sweep_forecast.json`, so run it only in a separate copy of the repository and compare its output with the committed file there (then run `sha256sum -c PREREGISTRATION_PHASE_C.sha256` in your working copy to confirm nothing frozen changed).
