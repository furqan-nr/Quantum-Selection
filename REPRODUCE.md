# Reproducing "Oracle Cost, Not the Scoring Function: An Empirical Study of Budgeted Test Prioritization for the Qiskit Transpiler"

Software Quality Journal submission (collection "Quantum Software Quality"). Authors: Furqan Nasir, Muhammad Arif Shah, Iftikhar Alam. Repository: https://github.com/furqan-nr/Quantum-Selection (MIT license), release v1.0.0 (placeholder). DOI: to be added (Zenodo). An earlier version of the study is arXiv:2609.35834.

## Setup

Python 3.11 or 3.12 is required (the lock pins numpy 2.4.x, which needs Python 3.11 or newer).

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r environment/requirements.lock        # pinned harness (Qiskit 2.4.2, matplotlib for the figures)
pip install -e .                                    # or: export PYTHONPATH=src
python -m pytest -q                                 # expect: 135 passed, 1 skipped
```

The skipped test is `tests/test_phase_e.py::test_runner_refuses_study_release_with_dryrun_options`, skipped by `tests/conftest.py` (which is not part of any pre-registration manifest). The test file is frozen by `PREREGISTRATION_PHASE_E.sha256`. The test checked, before data collection, that the Phase E runner refused to run a study release. Now that the study data exist, running it would write into `phase_e/data/runs/` and overwrite committed data. It passed before data collection.

All analysis scripts read the frozen labels and costs and run without transpilation. Run them from the repository root with `PYTHONPATH=src`. They never modify the frozen inputs (`data/`, `data_scaleup/`, `results/*_frozen.json`), but each one rewrites its own output file in `results/` (for example `scripts/revision_stats_extra.py` rewrites `results/revision_stats_extra.json`, and `scripts/forward_selector_eval.py` rewrites `results/forward_units/<input>_selectors.json`), and `scripts/plot_sqj_figures.py` writes the figures into `paper/sqj/`. Run them on a fresh clone, or check the effect with `git diff`: a faithful re-run leaves the committed JSON files unchanged. `python -m cart.cli evaluate` and `analyze` without `--out-results` write to new timestamped folders under `results/`; never pass a `*_frozen.json` path to `--out-results`.

## Where every table and figure comes from

Numbering follows the manuscript of 2026-10-19 with RQ7 and RQ8 integrated: the article has Tables 1-10 and Figs. 1-2, and Online Resource 1 (OR1) has Sections S1-S7, Tables S1-S33 and Fig. S1 (the former article Fig. 3, file `Fig3.*`).

| Manuscript item | Source file(s) | Command |
|---|---|---|
| Table 1 (corpus, budgets) | `configs/corpus_costhet.yaml`, `configs/budgets.yaml`, `data/profile_baseline/profiles.json` | frozen; see the `frozen_calibration_2026_08_07` block |
| Table 2 (RQ1 and RQ3: 9-event and 19-event selector comparison) | `results/evaluation_costhet_frozen.json`, `results/evaluation_scaleup_frozen.json`; random over 100 seeds: `results/revision_stats_extra.json` | `python -m cart.cli evaluate --split all --random-seeds 20`; `python -m cart.cli evaluate --data-dir data_scaleup --selectors scaleup --split all --random-seeds 20`; `python scripts/revision_stats_extra.py` |
| Table 3 (RQ2: composite with and without severity, under constant and cross-event costs) and OR1 Table S5 (full ablation and combiners) | `results/analyze-costhet-frozen.json`, `results/analyze-scaleup-frozen.json`, `results/revision_costscale.json` | `python -m cart.cli analyze --split all` (add `--data-dir data_scaleup` for 19 events); `python scripts/revision_costscale.py` |
| Table 4 (RQ4: frozen budgets in real seconds) and OR1 Fig. S1 | `results/revision_costscale.json` (`s5_frozen_budgets`); earlier percentage-of-suite view: `results/revision_budgeted.json` | `python scripts/revision_costscale.py`; figure: `python scripts/plot_sqj_figures.py` |
| Table 5 (RQ5: forward regressions) | `results/forward_units/fwd-applylayout-registers-14904_v2*.json`, `results/forward_units/hist-vf2postlayout-noop_v2_corrected*.json` | `python scripts/forward_selector_eval.py --event fwd-applylayout-registers-14904` and `--event hist-vf2postlayout-noop` (the defaults select the reported `_v2` / `_v2_corrected` input and the wall clock; add `--budget-basis post` for the `_postbudget` files) |
| Tables 6-7 (RQ6, Phase C: decision rules P1/P2, mean AUC per cost model) | `PREREGISTRATION_PHASE_C.md`, `configs/phase_c_cost_model.json`, `data_phase_c1/`, `data_phase_c2/`, `results/phase_c_confirmatory.json` | `python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup --out /tmp/phase_c.json` (see below) |
| Tables 8-9 (RQ7, Phase D: events; per-event P2, P1 spend, APFDc, detection; P1 criteria) | `PREREGISTRATION_PHASE_D.md`, `phase_d/events/phase_d_events.json`, `phase_d/data/`, `results/phase_d_confirmatory.json`; post hoc numbers of Section 6.3: `results/phase_d_exploratory_diagnostics.json` | `python phase_d/analysis/phase_d_analysis.py --out /tmp/phase_d.json` (see below); diagnostics: `python phase_d/analysis/phase_d_diagnostics.py`; number check: `python verification/check_phase_d_manuscript.py` |
| Table 10 (RQ8, Phase E: fresh release pairs; per-pair P2' suite-cost error, P1' spend, comparator) | `PREREGISTRATION_PHASE_E.md`, `phase_e/events/phase_e_pairs.json`, `phase_e/data/`, `results/phase_e_confirmatory.json`; development data and forecast: `phase_e/dev/estimator_selection.json`; post hoc numbers of Section 7.3: `results/phase_e_exploratory_diagnostics.json` | `python phase_e/analysis/phase_e_analysis.py --out /tmp/phase_e.json` (see below); number check: `python verification/check_phase_e_manuscript.py` |
| Figs. 1-2 and OR1 Fig. S1 (Fig. 2 from the scale-up evaluation, OR1 Fig. S1, file `Fig3.*`, from `results/revision_costscale.json`) | the results files above | `python scripts/plot_sqj_figures.py` |
| OR1 Tables S1-S3 (positioning, frozen `risk_score` configuration, mutation operators) | `configs/corpus_costhet.yaml`, `src/cart/selectors/`, `src/cart/events/mutations.py`, `src/cart/events/mutations_scaleup.py`, `PREREGISTRATION_PHASE_A.md` | n/a |
| OR1 Table S4 (per-event AUC, 9 events) and Table S8 (per-event AUC and detecting units, 19 events) | `results/evaluation_costhet_frozen.json`, `results/evaluation_scaleup_frozen.json` | as for Table 2 |
| OR1 Table S6 (detectability strata) | `results/revision_extra.json` | `python scripts/revision_extra.py` |
| OR1 Table S7 (paired tests under constant and cross-event costs) | `results/revision_costscale.json` | `python scripts/revision_costscale.py` |
| OR1 Table S9 (paired comparisons, Holm family of seven) | rows 1-7: `results/revision_stats_extra.json` (`F_paired_family7_random100`); last row: `results/revision_reanalysis.json` (`paired_tests.new10`) | `python scripts/revision_stats_extra.py`; `python scripts/revision_reanalysis.py` |
| OR1 Table S10 (event dependence, deduplicated and cluster-bootstrap tests); OR1 Section S2.5 (forward regressions under the study's own oracles) | `results/revision_dependence.json` | `python scripts/revision_dependence.py` |
| OR1 Section S2.4 (composite sensitivity under finite budgets) | `results/revision_budgeted.json` | `python scripts/revision_budgeted.py` |
| OR1 Tables S11-S13 (equivalence and Bayesian bootstrap, power, APFDc) | `results/revision_stats_extra.json` | `python scripts/revision_stats_extra.py` |
| OR1 Tables S14-S19 (Phase C operators, per-event AUC for C1 and C2, estimator accuracy, forecast vs realised, restart sensitivity) | `results/phase_c_confirmatory.json`, `environment/phase_c/verification/sweep_forecast.json`, `verification/phase_c_independent_check.md` | as for Tables 6-7 |
| OR1 Section S5, Tables S20-S25 (Phase D per-event detail, forecast checks, post hoc diagnosis, estimator variants, order of operations) | `results/phase_d_confirmatory.json`, `results/phase_d_exploratory_diagnostics.json`, `phase_d/data/budget_lock/`, `phase_d/data/collect/*/COMPLETE.json`, `phase_d/collection_notes.md` | `python scripts/gen_or1_phased.py` (writes `paper/sqj/or1_phased.tex`; `--check` compares) |
| OR1 Section S6, Tables S26-S33 (Phase E estimator selection, forecast, per-pair detail for three estimators, decisions, coverage and lane cost, post hoc diagnosis) | `results/phase_e_confirmatory.json`, `results/phase_e_exploratory_diagnostics.json`, `phase_e/dev/estimator_selection.json`, `phase_e/data/budget_lock/`, `phase_e/data/runs/`, `verification/phase_e_independent_check.md` | `python scripts/gen_or1_phasee.py --check` (without `--check` it rewrites `paper/sqj/or1_phasee.tex`) |
| Label counts (oracle tiers, detections, false positives) | `data/derived/labels.json`, `data_scaleup/derived/labels.json` | read the `oracle_strength`, `fault_id_detected`, `label` and `confirmed` fields |

Old-to-new numbering (manuscript of 2026-10-17 to restructured manuscript of 2026-10-18): Table 1 (positioning) moved to OR1 Table S1; Table 2 (configuration) to OR1 Table S2; Table 3 (corpus) is now Table 1; Table 4 (operators) moved to OR1 Table S3; Tables 5 and 8 (RQ1, RQ3) are merged into Table 2; Table 6 (RQ2) is now Table 3, with the full version in OR1 Table S5; Table 7 (strata) moved to OR1 Table S6; Table 9 (paired tests) moved to OR1 Table S9; Table 10 (RQ4) is now Table 4; Table 11 (RQ5) is now Table 5; Table 12 (Phase C operators) moved to OR1 Table S14, which already held the same rows; Tables 13 and 14 (RQ6) are now Tables 6 and 7. Former OR1 Tables S1-S13 are now S4, S8, S11, S12, S13, S7, S10, S14, S15, S16, S17, S18 and S19. Figures keep their numbers. RQ7 integration (2026-10-18, later the same day): new article Section 6 with Tables 8 and 9; Sections 6-9 (Discussion to Conclusion) became 7-10; new OR1 Section S5 (Tables S20-S25), the former S5 (Reproduction) is now S6. No earlier table changed its number. RQ8 integration (2026-10-19): new article Section 7 with Table 10; Sections 7-9 (Discussion to Conclusion) became 8-10; new OR1 Section S6 (Tables S26-S33), the former S6 (Reproduction) is now S7. No earlier table changed its number. Final check (2026-10-19): article Fig. 3 (spend relative to the frozen budgets, a plot of Table 4) moved to OR1 as Fig. S1, keeping its file name `Fig3.*`. No table changed its number.

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

The pre-registration `PREREGISTRATION_PHASE_C.md` and the files listed in `PREREGISTRATION_PHASE_C.sha256` were frozen and pushed to the public repository (commit `36a5bbb`, 2026-10-16) before any Phase C label existed. Do not edit them: any change is a deviation under Section 11 of the record (the pre-registration record's own numbering).

1. Check the frozen files: `sha256sum -c PREREGISTRATION_PHASE_C.sha256` (all 28 entries must report OK).
2. Re-run the confirmatory analysis on the committed labels, writing to a new file:

   ```bash
   PYTHONPATH=src python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup --out /tmp/phase_c.json
   ```

   Apart from `runtime_s` and the absolute paths it records, the output equals `results/phase_c_confirmatory.json` (the independent check found it byte-identical under two `PYTHONHASHSEED` values). Never point `--out` at the committed file.
3. Relabeling (optional, several hours per cohort): `scripts/run_phase_c_ground_truth.py` with C1 under Qiskit 2.4.2 (the main lock) and C2 under Qiskit 2.2.3 (`environment/phase_c/requirements-qiskit-2.2.3.lock.txt`). The labels in the repository were produced on the machine recorded in `environment/phase_c/labeling_environment.txt`, calling the driver's chunk mode one pair at a time through `environment/phase_c/run_slice.py` (which reads per-unit time predictions from `environment/phase_c/unit_cost_B.json`; adjust the two absolute paths at its top). The deviation during C2 (a sandbox restart after 1,126 of 1,160 pairs) and its sensitivity analysis are in `verification/phase_c_independent_check.md`.
4. The registered sweep forecast can be regenerated with `python environment/phase_c/sweep_forecast.py` (inputs: the transpilation-only sweeps in `environment/phase_c/verification/`). Caution: the script writes to the committed, frozen `environment/phase_c/verification/sweep_forecast.json`, so run it only in a separate copy of the repository and compare its output with the committed file there (then run `sha256sum -c PREREGISTRATION_PHASE_C.sha256` in your working copy to confirm nothing frozen changed).

## Phase D: pre-registered study on Qiskit's own tests and real regressions (RQ7)

The pre-registration `PREREGISTRATION_PHASE_D.md` and the files listed in `PREREGISTRATION_PHASE_D.sha256` were pushed to the public repository (commit `32e53d4`) before any per-test duration of a study release was measured. The budget locks (`phase_d/data/budget_lock/`) were pushed in commit `a3c1148` (D1-D4, D6-D8, commit time 2026-10-18 01:22:43 UTC) and `25ad1e3` (D5, commit time 02:15:45 UTC) before the corresponding buggy releases were timed (earliest B timing records 01:24:03 for 2.0.2 and 05:46:06 for 2.5.1, sandbox clock). The commit times were checked against the GitHub API. They are set by the committing machine, not by GitHub on receipt, so the 80-s margin for 2.0.2 assumes that the two clocks agree to within about a minute. `phase_d/collection_notes.md` records the order of operations, including the order note (F checks of seven events ran before the 2.5.1 timing passes). Do not edit the frozen files, `phase_d/data/` or `results/phase_d_confirmatory.json`.

1. Check the frozen files: `sha256sum -c PREREGISTRATION_PHASE_D.sha256` (all entries must report OK).
2. Re-run the confirmatory analysis on the committed runs, writing to a new file (standard library only):

   ```bash
   python phase_d/analysis/phase_d_analysis.py --out /tmp/phase_d.json
   ```

   The output equals `results/phase_d_confirmatory.json` (the independent check found it byte-identical under `PYTHONHASHSEED=0` and `12345`). Never point `--out` at the committed file, and never pass `--lock` (locks are written once and the script refuses to rewrite them).
3. Independent recomputation of P1 and P2 without the analysis code: `python verification/phase_d_recompute_p1p2.py`. Report: `verification/phase_d_independent_check.md`.
4. Post hoc diagnostics (exploratory, written after the confirmatory run): `python phase_d/analysis/phase_d_diagnostics.py`. It rewrites `results/phase_d_exploratory_diagnostics.json`, so run it on a fresh clone and compare.
5. Manuscript numbers: `python scripts/gen_or1_phased.py --check` (OR1 Section S5 equals its generator output; without `--check` the script rewrites `paper/sqj/or1_phased.tex`) and `python verification/check_phase_d_manuscript.py` (every RQ7 number in the article, the abstract length and the cover-letter figure against the results files). Both need the manuscript sources under `paper/sqj/` and `paper/build_cover_letter_sqj.js`, which are distributed with the submission (Overleaf archive) rather than in this repository.
6. Re-collecting the timings (optional, about 2.5-3.5 hours serial): `phase_d/runner/run_phase_d.py` with the PyPI wheels and source distributions whose SHA-256 are frozen in `phase_d/config/phase_d_config.json`; follow Section 12 of the pre-registration. Fresh timings will differ from the committed ones by machine noise, so compare decisions, not digits. `phase_d/tools/auto_d.py` is the step driver used in the collection sandbox. Its two paths are sandbox-absolute and must be adjusted before reuse.

## Phase E: pre-registered new-test-aware estimator on fresh release pairs (RQ8)

The pre-registration `PREREGISTRATION_PHASE_E.md` and the files listed in `PREREGISTRATION_PHASE_E.sha256` were pushed to the public repository (commit `dfc413c`, commit time 2026-10-18 21:59:09 UTC) before any Phase E release was installed or timed. All Phase D data served as development data: the estimator was chosen by leave-one-pair-out on Phase D's six release pairs (`phase_e/dev/select_estimator.py`, output `phase_e/dev/estimator_selection.json`, frozen with the record). The ten budget locks (`phase_e/data/budget_lock/`) were pushed in commit `8e81ea8` (commit time 22:59:42 UTC), recorded by the runner in `LOCK_PUSHED.json`, before any B timing pass (earliest B record 23:00:31, sandbox clock). As for Phase D, commit times are set by the committing machine, so the 49-s margin assumes the two clocks agree to within well under a minute. Do not edit the frozen files, `phase_e/data/` or `results/phase_e_confirmatory.json`.

1. Check the frozen files: `sha256sum -c PREREGISTRATION_PHASE_E.sha256` (all entries must report OK).
2. Re-run the confirmatory analysis on the committed runs, writing to a new file (standard library only):

   ```bash
   python phase_e/analysis/phase_e_analysis.py --out /tmp/phase_e.json
   ```

   The output equals `results/phase_e_confirmatory.json` (byte-identical under `PYTHONHASHSEED=0` and `12345` in the independent check). Never omit `--out` (the default is the committed results file), and never pass `--lock`.
3. Independent recomputation without the analysis code, with the integrity, timeline and completeness checks: `python verification/phase_e_recompute.py` (exit code 0 when every check passes). Report: `verification/phase_e_independent_check.md`. One timeline check (`all_P_runs_and_B_collects_precede_lock_writing`) compares file modification times. Git does not preserve them, so on a fresh clone this check fails and the script exits with status 1. Every other check is meaningful on a clone. The modification-time check passes only on the original files (the authors' working copy).
4. Post hoc diagnostics (exploratory, written after the confirmatory run): `python phase_e/analysis/phase_e_diagnostics.py`. It rewrites `results/phase_e_exploratory_diagnostics.json` and reads the raw per-test records under `phase_e/data/runs/`, so run it on a fresh clone and compare.
5. Estimator selection on development data: `python phase_e/dev/select_estimator.py` rewrites the frozen `phase_e/dev/estimator_selection.json`. Run it only in a separate copy of the repository, compare, and confirm with `sha256sum -c PREREGISTRATION_PHASE_E.sha256` that nothing frozen changed in your working copy.
6. Manuscript numbers: `python scripts/gen_or1_phasee.py --check` (OR1 Section S6 equals its generator output) and `python verification/check_phase_e_manuscript.py` (every RQ8 number in the article, the abstract length, the RQ8 style rules and the cover-letter figures against the sources). Like the Phase D checks, they need the manuscript sources under `paper/sqj/` and `paper/build_cover_letter_sqj.js`.
7. Re-collecting the timings (optional, about 4-5.5 hours serial): `phase_e/runner/run_phase_e.py` with the PyPI wheels and source distributions whose SHA-256 are frozen in `phase_e/config/phase_e_config.json`; follow Section 12 of the pre-registration. Compare decisions, not digits. `phase_e/tools/auto_e.py` is the sandbox step driver, with sandbox-absolute paths to adjust before reuse, as for Phase D.
