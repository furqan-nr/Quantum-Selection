# Quantum Selection: reproduction package

Code, frozen data, configurations, environment recipes and analysis scripts for

> **Oracle Cost, Not the Scoring Function: An Empirical Study of Budgeted Test Prioritization for the Qiskit Transpiler**
> Furqan Nasir, Muhammad Arif Shah, Iftikhar Alam. Submitted to the Software Quality Journal.

An earlier version of the study is available as arXiv:2609.35834. Repository: https://github.com/furqan-nr/Quantum-Selection. License: MIT (`LICENSE`). Release: v1.0.0. DOI: [10.5281/zenodo.23475857](https://doi.org/10.5281/zenodo.23475857). Citation metadata: `CITATION.cff`.

**Start with `REPRODUCE.md`**, which maps every table and figure of the manuscript to its source file and command.

## The study

- **Discovery phase (RQ1-RQ5).** A transparent cost-aware selector (`risk_score`) is compared with random, cheapest-first, diversity, history and change-stage orderings on a 9-event mutation cohort and a separately pre-specified 19-event scale-up (RQ1, RQ3), with an ablation of the severity term under constant and cross-event costs (RQ2), frozen budgets in real seconds (RQ4) and two verified forward regressions (RQ5).
- **Three pre-registered confirmation studies.** Each record and its frozen files were pushed to this repository before the data it governs existed.
  - **RQ6, Phase C** (`PREREGISTRATION_PHASE_C.md`): synthetic units on two Qiskit versions. The cost claims were supported.
  - **RQ7, Phase D** (`PREREGISTRATION_PHASE_D.md`): Qiskit's own test suite on 8 real regressions. Both claims failed.
  - **RQ8, Phase E** (`PREREGISTRATION_PHASE_E.md`): a new-test-aware cost estimator on 10 fresh release pairs. The suite-cost claim was supported. The per-pair budget claim failed on one pair.

## Contents

- `src/cart/`: the prototype (CLI, manifests, events, oracles, selectors, metrics, validity gates).
- `configs/`: frozen, pre-declared configuration (budgets, corpus, thresholds, stage map, cutoff, seeds, Phase C cost model).
- `data/`: the primary 9-event corpus (event ledger, manifests, calibrated cost profiles, write-once raw evidence, derived labels).
- `data_scaleup/`: the independently frozen 19-event scale-up corpus (same layout).
- `data_phase_c1/`, `data_phase_c2/`: Phase C labels (Qiskit 2.4.2 and 2.2.3).
- `phase_d/`: Phase D (RQ7) configuration, events, runner, collected data, budget locks, analysis.
- `phase_e/`: Phase E (RQ8) configuration, release pairs, development data, runner, collected data, budget locks, analysis.
- `environment/`: harness lock (`requirements.lock` and its hash), per-event Qiskit build locks, setup recipes, Phase C labeling environment.
- `results/`: result files reported in the paper (frozen evaluations, post hoc analyses `revision_*.json`, forward-regression units `forward_units/`, Phase C/D/E confirmatory and diagnostic outputs, `costcurve-sandbox/` cited by `CORPUS_DESIGN_B1.md`).
- `scripts/`: analysis, figure and verification scripts.
- `tests/`: automated test suite.
- `verification/`: independent re-checks of Phases C, D and E.
- Top-level documents: `REPRODUCE.md`, `METHODOLOGY.md`, `PREREGISTRATION_PHASE_{A,C,D,E}.md` (and `.sha256` manifests for C, D, E), `PHASE_D_CANDIDATES.md`, `CORPUS_DESIGN_B1.md`, `KAGGLE_CALIBRATION.md` with `kaggle_calib*.ipynb` and `kaggle_bundle*.zip`, and forward-event provenance notes (`FORWARD_EVENTS_B2.md`, `FORWARD_COUNT_DECISION.md`, `BISECTION_AUDIT.md`, `FWD_15024_RETRACE.md`, `TRIGGER_15024_FROM_FIXTEST.md`, `RISK_SCORE_INDEPENDENCE.md`).

## Setup and tests

Python 3.11 or 3.12 is required (the lock pins numpy 2.4.x).

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r environment/requirements.lock
pip install -e .                                    # or: export PYTHONPATH=src
python -m pytest -q                                 # expect: 135 passed, 1 skipped
```

The skipped test (`tests/test_phase_e.py::test_runner_refuses_study_release_with_dryrun_options`) is skipped by `tests/conftest.py`. Its test file is hash-frozen, and with the study data present the test would write into `phase_e/data/runs/`. It passed before data collection.

Check the frozen files with `sha256sum -c PREREGISTRATION_PHASE_C.sha256` (likewise `_D`, `_E`). `.gitattributes` keeps these files byte-exact (no end-of-line conversion). Analysis scripts rewrite their own outputs in `results/`, so run them on a fresh clone and compare with the committed files (see `REPRODUCE.md`).

## Known limitations of the package

- **Manuscript-dependent tools.** `verification/check_phase_d_manuscript.py`, `verification/check_phase_e_manuscript.py`, `scripts/gen_or1_phased.py`, `scripts/gen_or1_phasee.py` and `scripts/plot_sqj_figures.py` read or write the manuscript sources under `paper/`, which are not distributed here. Without them the checkers fail and `--check` reports a difference.
- **Phase A hash of `src/cart/cli.py`.** `PREREGISTRATION_PHASE_A.md` records eight hashes. Seven match. The recorded hash of `src/cart/cli.py` does not match the current file or any committed version (commits `a6e4802` and `b589d0d`): `cli.py` was extended after the Phase A record. The Phase A results were produced by the frozen evaluation files listed in that record (selector, operators, metrics, gates and their tests), whose hashes match.
- **Modification-time check.** `verification/phase_e_recompute.py` includes one timeline check based on file modification times. Git does not keep them, so on a fresh clone that check fails and the script exits with status 1. The check needs the original files. All other checks run normally.
- **Sandbox paths.** `phase_d/tools/auto_d.py`, `phase_e/tools/auto_e.py` and `environment/phase_c/run_slice.py` contain absolute paths of the collection environment. Adjust them before reuse. Some raw logs and result files record such paths as provenance.
- **Planning documents.** Some comments and frozen documents refer to internal planning notes (for example `PAPER2_PLAN.md`) that are not distributed. The manuscript, figures and cover letter are also excluded.
