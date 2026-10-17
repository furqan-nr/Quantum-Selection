# Phase D pre-registration: budgeted test selection on Qiskit's real transpiler unit-test suite with real regressions

**Date of record: 2026-10-18** (UTC timestamp and file hashes in `PREREGISTRATION_PHASE_D.sha256`). The record becomes
external only when the user pushes these files to the public repository (GitHub commit timestamp) or deposits them
(OSF/Zenodo). Until then the SHA-256 manifest is evidence of content, not of time.

**State of knowledge at the time of record.** No per-test duration of any Phase D study release (P, B or F of any
event, Section 4) has been measured. No selection, ordering, budget or APFDc statistic has been computed on any study
release. What HAS been observed before this record, and is disclosed in full in Section 10: the pass/fail outcome of
each event's detecting test on its release pair (the 2026-10-18 pilot), one full transpiler+compiler slice run on
2.2.2 and one on 2.2.3 with FILE-LEVEL wall times only, the collected-test counts of 2.2.3 and 2.5.2, a re-check that
D7's hang also occurs with `RAYON_NUM_THREADS=1`, PyPI metadata, and a dry run of the runner on Qiskit 2.3.0/2.3.1 and
synthetic tests (outside the study). Because the existence and pass/fail status of the detecting tests are already
known, no claim about them is confirmatory. The confirmatory claims concern quantities nobody has measured: the
per-test costs of the study releases, how well the previous release's costs estimate them, and where each policy
places the detecting test in cost terms.

---

## 1. Motivation and research question

The manuscript (`paper/sqj/main.tex`) argues that knowledge of oracle and test cost, not the scoring function, drives
budgeted test selection, and Phase C confirmed on 116 synthetic transpiler units and 20 mutation events that an
estimator built from earlier measurement sessions predicts the new costs and keeps budgeted selection within budget.
All of that used the study's own synthetic units and injected faults. Phase D asks whether the cost argument holds on
the artefact practitioners actually run: Qiskit's own transpiler and compiler unit tests, with real regressions that
shipped in Qiskit releases.

**RQ7.** On Qiskit's own transpiler test suite and real regressions, does selection budgeted with a cost estimate taken
from the previous release's measured test durations (a) respect a time budget in real seconds, and (b) reach the
fault-revealing test earlier, and within budget more often, than cost-blind orderings?

## 2. What is observed and what is not

| | Already observed (disclosed, Section 10) | Not observed (confirmation data) |
|---|---|---|
| Detecting tests | pass/fail of each backported test on B and F (pilot) for all 8 events; D7 hang under pinning | outcomes in the registered environment (forecast check F1) |
| Pre-existing tests | 2.2.2 full slice: no fault-related failure for D1 | whether any pre-existing test reveals D2-D8 (forecast check F2) |
| Costs | file-level wall times of the 2.2.2 and 2.2.3 slices (one run each); backport durations on 2.3.1 (not a study release) | every per-test duration of every study release (P, B, F) |
| Statistics | none | estimator error, budgets, spend, APFDc, detection within budget |

## 3. Test suite and the mapping of the paper's selectors

**Suite.** The test tree shipped in each release's sdist (`qiskit-X.tar.gz`, SHA-256 frozen in
`phase_d/config/phase_d_config.json`): every `test_*.py` under `test/python/transpiler/` (recursive) and
`test/python/compiler/`, minus `test/python/transpiler/test_unitary_synthesis_plugin.py` (7 environmental failures,
its test plugins are registered only by a development install). Tests are collected and run by pytest; ddt-expanded
cases are separate tests. Test identity across releases is the **normalized node id**: every `0x` followed by at least
6 hex digits is replaced by `0x?` (ddt names embed object addresses), and a repeated id gets a `#k` suffix.

**Event suite.** For event e, `S_e` = the collect-only list of B's slice plus the event's own backported tests under
their logical ids (Section 5). Backported tests of other events that share B are not part of `S_e`.

**Mapping of the selectors to unit tests.** The paper's selectors use features of its synthetic units (circuit family,
backend, width, oracle tier, stage, severity) that unit tests do not have. The mapping is:

| Paper concept | Unit-test analogue in Phase D | Rationale |
|---|---|---|
| unit cost (transpilation + oracle) | per-test wall time, setup + call + teardown, as reported by pytest | the CI cost of a unit test; there is no separate oracle |
| previous-session cost estimate | the test's duration in the previous release's run (P) | the deployable analogue: a CI system has last release's timings |
| coverage key (family, backend[, tier]) | logical test file (module) | files group the tests of one pass or component (`test_vf2_layout.py`, ...), the closest analogue of "which part of the compiler a unit exercises"; tier does not exist |
| `diversity_only` / COAST | `coast_d`: COAST's loop (`src/cart/selectors/coast.py`) with key = file, cost = estimate, ties by CI order, no severity | identical algorithm, mapped key |
| `cheapest_first` | ascending estimate, ties by CI order | identical |
| `random` | uniform permutation of the suite, 100 seeds | identical |
| cost-blind default | CI order: files in sorted path order, tests in pytest collection order, each backported test at the end of its logical file | what `pytest test/python/transpiler test/python/compiler` runs |
| cost-blind diversity | `file_rr`: round robin over files in sorted order, next test in collection order | diversity without cost knowledge |
| width, stage, change_stage, history_only, severity, composite `risk_score` | **not applicable, not run** | unit tests have no circuit width or stage; mapping file names to stages would be ad hoc; history needs failure history the releases do not provide; the composite needs width and severity |

## 4. Events

Eight of the ten candidates in `PHASE_D_CANDIDATES.md`, every one with a buggy release (B) and a fault-free reference
release (F) on PyPI that the sandbox can install. P is fixed by rule: **the latest final 2.x release uploaded to PyPI
before B** (upload times frozen in the config). F is the release that contains the fix. Ledger:
`phase_d/events/phase_d_events.json`.

| Event | Candidate, fault (fix PR) | Type | P (estimate) | B (under test) | F (reference) | Detecting test (backported) | Pilot on B |
|---|---|---|---|---|---|---|---|
| D1 | C1 ConsolidateBlocks instance reuse (#15258) | functional | 2.2.1 | 2.2.2 | 2.2.3 | `compiler/test_transpiler.py::TestTranspile::test_reuse_on_differing_circuits` (ddt 0-3) | 2 of 4 fail |
| D2 | C2 VF2PostLayout at O3 runs with no effect (#14120, #14867) | performance / contract | 2.0.3 | 2.1.0 | 2.1.2 | ADDED test `TestNoVF2WithInitialLayout` (#14867 reproducer), logical file `transpiler/test_preset_passmanagers.py` | 1 of 4 fail |
| D3 | C3 ApplyLayout drops registers (#15024) | metadata / contract | 2.1.2 | 2.2.0rc1 | 2.2.3 | `test_preset_passmanagers.py::TestPresetPassManager::test_layout_registers_preserved[_with_allocated_ancilla]` | 8 of 8 fail |
| D4 | C4 CommutativeCancellation negative X rotations (#16599) | semantic | 2.4.2 | 2.5.0 | 2.5.1 | `test_commutative_cancellation.py::...::test_negative_x_rotations` (ddt 2,3,4) | 2 of 3 fail |
| D5 | C5 OptimizeCliffordT S/Sdg swap (#16729) | semantic | 2.5.0 | 2.5.1 | 2.5.2 | `test_clifford_t_passmanager.py::...::test_clifford_t_transpile_is_unitarily_equivalent` (ddt 0-3) | 3 of 4 fail |
| D6 | C6 VF2Layout max_trials negative (#14667) | crash / API contract | 2.0.3 | 2.1.0 | 2.1.1 | `test_vf2_layout.py::TestVF2LayoutLattice::test_hexagonal_lattice_graph_9_in_25_no_trial_limit` (ddt) | 2 of 2 fail |
| D7 | C7 Optimize1qGatesDecomposition GIL deadlock (#16592) | crash (hang) | 2.4.2 | 2.5.0 | 2.5.1 | `test_optimize_1q_decomposition.py::...::test_custom_gate_in_target` | hangs |
| D8 | C8 ElidePermutations with PermutationGate (#14603) | semantic | 2.0.1 | 2.0.2 | 2.0.3 | `test_elide_permutations.py::TestElidePermutationsInTranspileFlow::test_unitary_equivalence_permutation_gates` | fails |

Excluded: C9 (regression status unproven, introducing change unknown) and C10 (no release pair). Two pairs of events
share B (D2/D6: 2.1.0; D4/D7: 2.5.0), so their real costs come from the same runs. They are separate events because
their faults and detecting tests differ; an exploratory analysis averages each pair into one cluster (Section 9.4).

**The near-circularity, stated plainly.** Every introducing change passed Qiskit's CI, so by construction no
pre-existing test is expected to reveal these faults, and the only known revealing test is the fix's regression test
(or, for D2, a test added by us before this record). Phase D therefore does **not** measure whether a revealing test
exists. It measures, for a revealing test that is assumed to be part of the suite when B is tested, (i) where each
policy places it in cost terms and (ii) whether it fits a real-time budget. This is the classical regression-test
prioritisation setting in which the fault-revealing tests are known after the fact. Whether any pre-existing test
reveals the fault is reported separately (forecast check F2). The revealing test is new in every event, so it has no
previous-release duration and the estimator must price it by the unseen-test rule (Section 7). This is realistic: in
CI the test that catches a regression is often the newest one.

## 5. Backported detecting tests (exact text)

`phase_d/backports/test_backport_d{1..8}.py`, generated by `phase_d/tools/make_backports.py` from the fix releases'
sdists (SHA-256 checked against PyPI). Each file contains the fix-release test method(s) **verbatim** (decorators,
docstring, body; source file SHA-256 and line ranges in the header), placed in a subclass of the **buggy release's own**
test class of the same name, so helpers, attributes and `setUp` come from the version under test. Inherited tests are
hidden (set to `None`), so only the backported methods run. Module-level names the methods use are imported exactly as
the fix-release module binds them. D2 is our added file, copied unchanged from
`phase_d/sandbox_helpers_2026-10-18/test_added_14120.py` (written 2026-10-18, before this record). In the timing passes
a backported file runs in the same pytest process right after its logical file (warm process, as if appended to that
file), and its tests carry the logical id `<logical file>::<Class>::<method>` for ordering, estimation and analysis.

## 6. Measurement protocol

### 6.1 Runner

`phase_d/runner/run_phase_d.py` (standard library), pytest plugin `phase_d/runner/phased_plugin.py`, calibration
`phase_d/runner/calibrate.py`.

- **Environment.** One venv per Qiskit version (Python 3.10), the release's manylinux wheel (SHA-256 frozen) plus
  `ddt`, `hypothesis`, `pytest`, all third-party packages pinned identically (`phase_d/config/constraints.txt`). Tests
  run from a directory holding only the sdist's `test/` tree. Single-thread pinning: `RAYON_NUM_THREADS`,
  `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS` = 1, `QISKIT_PARALLEL=FALSE`,
  `QISKIT_NUM_PROCS=1`, `PYTHONHASHSEED=0`. Serial execution (pytest-xdist breaks on ddt names).
- **Units.** One pytest process per slice file, files in sorted order. Every test's start and result are written as
  JSON lines immediately (nothing is lost when a process is killed).
- **Per-test timeout 60 s.** A test running longer is killed (process group), recorded as `timeout` with duration 60 s,
  and the file is relaunched with the completed and timed-out tests deselected. A process that dies inside a test
  records that test as `crash`.
- **Chunking and resumption.** A call stops launching files after 115 s and kills at 145 s; the next call resumes,
  deselecting completed tests. (Dry run: external kill and resumption verified, Section 10.)
- **Environment record per call**: UTC time, host, CPU model, core count, load, pinned variables, runner file hashes,
  venv `pip freeze` hash, and the calibration time (median of 5 repetitions of a fixed workload).

### 6.2 Runs

| Run | Releases | Passes | Purpose |
|---|---|---|---|
| P timing | 2.0.1, 2.0.3, 2.1.2, 2.2.1, 2.4.2, and 2.5.0 (P of D5) | pass 1 | estimator (P's own slice files only, backport records never used) |
| B collect-only | 2.0.2, 2.1.0, 2.2.0rc1, 2.2.2, 2.5.0, 2.5.1 | 1 | event suite, budget lock, speed factor |
| B timing | same six | passes 1 and 2 | real costs, outcomes (pass 1 of 2.5.0 doubles as D5's P run) |
| F check | 2.0.3, 2.1.1, 2.1.2, 2.2.3, 2.5.1, 2.5.2 | 1 | the event's backported tests and every pre-existing test that did not pass on B in some pass, run from B's test tree against the F wheel |

P is timed once because a CI system has one previous run; B is timed twice to average noise and to measure it.

### 6.3 Machine

All runs on the development sandbox (Linux, 2 vCPU, Intel i7-11800H, Python 3.10). If the collection must move, all
runs of an event (P, B, F) are made on one machine; otherwise the speed rule applies.

### 6.4 Speed rule

k = calibration time of B's collect-only call / median calibration time over P's run calls. If k is outside
[0.8, 1.25], every estimate and both budgets of the event are multiplied by k. k never uses a test duration of B.

## 7. Cost estimator, real cost and budgets (frozen in `phase_d/config/phase_d_config.json`)

- **est(t)** for t in S_e: the P pass-1 duration of the same normalized id (timeouts = 60 s). **Unseen tests** (no P
  record): the median P duration of the seen tests of the same logical file if that file has at least 3 seen tests,
  otherwise the global median of all P durations. Rationale: a CI system pricing a new test knows its file. The
  median is robust to the heavy right tail of test durations. Applied identically to the backported tests and to
  every other new test. Then times k if the speed rule fires.
- **Real cost r(t)**: mean over the B timing passes of setup + call + teardown (timeout = 60 s). A suite test without
  any B record is charged its estimate and counted (`n_imputed_real`, reported, expected 0).
- **Budgets**: b_f = f x sum over S_e of est(t), f = 0.05 ("pr") and 0.25 ("nightly"); f = 0.50 exploratory. A budget
  is a fraction of the suite cost the selector believes in, as in Phase C rule E. 25% instead of Phase C's 50%:
  cost-ordered policies on unit tests can cover most tests at 50%, which would make every policy detect.
- **Budget lock.** Budgets cannot be frozen as numbers today because they depend on P durations nobody has measured.
  They are a deterministic function of frozen code, P's pass 1 and B's collect list, and they are **locked before
  B's timing passes**: `python phase_d/analysis/phase_d_analysis.py --lock <events>` writes
  `phase_d/data/budget_lock/<E>.json` (input hashes, suite size, k, total estimate, budgets) and refuses if a B pass
  exists. The final analysis recomputes them and asserts equality. D5's lock is written after 2.5.0's passes (2.5.0 is
  D5's P) and before 2.5.1's.

## 8. Policies, execution model and metrics

- **Cost-blind policies** (`default`, `random`, `file_rr`) are executed in order under a **real time box** of b_f
  seconds: a test counts as executed if the cumulative real cost up to and including it is at most b_f (the running
  test is killed at the budget). This is how a time-boxed CI job without cost knowledge behaves.
- **Cost-aware policies** (`cheapest_first`, `coast_d`) **plan** a selection with their estimates: greedy over their
  order, a test is selected if the cumulative estimate stays within b_f (skip otherwise, COAST's rule). The plan is
  charged its real cost (budget compliance), and it is executed under the same real time box (detection).
- **Reference** (`cheapest_oracle`, real costs): exploratory upper reference, never compared confirmatorily.
- **Detecting set** D_e: tests of S_e that did not pass (failed, error, timeout or crash) in every B timing pass with a
  record and passed on F. A test that cannot be collected on B is absent from S_e.
- **Metrics per event x policy.** Detection within budget (0/1; random: probability over 100 seeds); real spend /
  budget of the plan; single-fault APFDc of the full order, `1 - (C_before + r_first/2) / C_total` with real costs,
  0 if D_e is empty (random: mean over 100 seeds); rank and real cost to the first detecting test. APFDc values are
  rounded to 6 decimals before differences; a zero difference is a tie.

## 9. Roles of the analyses, hypotheses and decision rules

### 9.1 Confirmatory family

Evaluated by the frozen `phase_d/analysis/phase_d_analysis.py` on all analysable events. **Every result is reported
whatever its direction.**

- **P1 (budget compliance in real seconds, RQ7a; decision rule).** For `cheapest_first` and `coast_d` planned with the
  previous-release estimator, at f = 0.05 and f = 0.25: mean over events of real spend / budget <= 1.25 AND no event
  > 2.0. Supported iff all four policy x tier criteria hold. Not a significance test (min-p not applicable). Why it can
  fail: per-test durations change between releases (Rust ports, new parametrisations), new tests are priced by a file
  median, and at 5% the plan holds thousands of millisecond tests whose sum is sensitive to systematic shifts. Phase C
  reference (synthetic units): 0.91.
- **P2 (suite-cost estimate transfer; decision rule).** For every event, |sum est / sum r - 1| <= 0.25. Why it can
  fail: the 2.4.2 -> 2.5.0 and 2.1.2 -> 2.2.0rc1 steps cross a minor release (2.2.3 collects 2679 tests, 2.5.2 7686),
  so many tests are unseen and priced by the rule. Note: the 2.2.2 and 2.2.3 file-level slice wall times (122 s and
  129 s, one run each) are already known; they are not per-test, not P-to-B pairs of any event (2.2.3 is an F
  release), and include per-process overhead, but they make P2 for D1 less uncertain than for the other events.
- **H1 (coast_d before the CI default, RQ7b).** d_e = APFDc(coast_d) - APFDc(default) > 0.
- **H2 (coast_d before random ordering, RQ7b).** d_e = APFDc(coast_d) - mean APFDc(random).
  Test for H1 and H2: exact one-sided Wilcoxon signed-rank over events (zeros dropped, mid-ranks), Holm over {H1, H2}
  at familywise alpha = 0.05; supported iff Holm rejects AND the mean difference is > 0. The sign test is reported
  as a secondary statistic. **Power (minimum achievable p).** With n informative events the smallest exact one-sided
  p is 2^-n: n = 8: 0.0039; 7: 0.0078; 6: 0.0156; 5: 0.031. The first Holm step needs p < 0.025: with n = 8, W+ >= 33
  of 36 (at most one loss, of rank <= 3); with n = 6, all six must be wins; **with n <= 5 neither H can be supported**.
  The second step needs p < 0.05 (n = 8: W+ >= 31).
- **D1 (detection within budget, RQ7b; decision rule, because a paired binary test on 8 events is underpowered:
  McNemar exact one-sided min-p = 2^-k with k discordant events <= 8).** At f = 0.05 and f = 0.25, the number of events
  detected by `coast_d` (time-boxed) is >= that of `default`, >= that of `file_rr`, and >= the expected count of
  `random`; and it is strictly greater than `default` at least at one tier. Supported iff all hold. The McNemar exact
  p (coast_d vs default) is reported for each tier.

The confirmatory policy is `coast_d` because COAST is the paper's method carried over; `cheapest_first` enters P1 and
is compared exploratorily. Refutation of any claim is reported as such, and no claim is reinterpreted.

**No forecast of P1, P2, H1, H2 or D1 was computed.** It could not be: no per-test duration of any study release
exists. The only cost information about study-adjacent material is listed in Section 10. The positions of the
logical files in the CI order are derivable from file names alone (no execution); we did not compute default-order
ranks or costs.

### 9.2 Registered forecast checks (not confirmatory; outcome largely known)

- **F1** Backported-test outcomes reproduce the pilot (ledger field `pilot`): per event, the set of failing ddt cases on
  B and all passing on F. Reported per event with agreement.
- **F2** No pre-existing test reveals any event (forecast: 0 of 8 events; observed 0 for D1 on 2.2.2).
- **F3** D7's detecting test times out on B (60 s); if b_0.05 of D7 is below 60 s, D7 is undetectable within the pr
  budget for every policy (a tie by construction), and this is stated, not counted as a policy effect.
- **F4** The speed factor stays inside [0.8, 1.25] for every event (same machine).

### 9.3 Mechanism checks (true by construction; never evidence)

M1: every backported detecting test is unseen in P and priced by the unseen rule (file median). M2: cost-blind
time-boxed spend <= 1.0 and `cheapest_oracle` planned spend <= 1.0 by construction.

### 9.4 Exploratory (pre-declared, no confirmatory claim)

f = 0.50; cost-blind orders planned with the estimate (prefix); detection of the plan without the time box;
`cheapest_first` in every comparison; `cheapest_oracle`; alternative unseen rules (global median only, file mean, zero
cost); 10-s timeout sensitivity; per-pass spend (noise); per-test estimator accuracy (median absolute percentage error
over seen tests >= 10 ms, Spearman); share of the estimate on unseen tests; default order with the backported test at
the START of its file; version-cluster sensitivity (D2/D6 and D4/D7 averaged, 6 clusters); rank and seconds to first
detection; per-file runner overhead.

## 10. Disclosure of pre-registration-time computations

1. **2026-10-18 candidate search and pilots** (`PHASE_D_CANDIDATES.md`): fix-test pass/fail on the wheel pairs for all
   eight events (ledger `pilot`), including P or F outcomes where listed. Full transpiler+compiler slice runs on 2.2.2
   (B of D1) and 2.2.3 (F of D1 and D3) with a per-file loop: file-level wall times and pytest summaries only
   (`phase_d/sandbox_helpers_2026-10-18/prior_observations/`, 106 files each, 122.2 s / 129.1 s wall, 96.9 s /
   100.6 s pytest-reported). Collected-test counts of 2.2.3 (2679) and 2.5.2 (7686). The sandbox helpers of that day
   are archived in `phase_d/sandbox_helpers_2026-10-18/` (`slice.sh`, the D2 added test, `conftest.py`, two reproducer
   scripts).
2. **D7 pinning check (today)**: a standalone copy of D7's fix test on 2.5.0 still hung (killed at 40 s) under
   `RAYON_NUM_THREADS=1` and `=2` (`c7_pinning_check_test.py`). Needed to know whether single-thread pinning removes the
   fault; it does not.
3. **Backport generation (today)**: reading the fix releases' test sources (2.0.3, 2.1.1, 2.2.3, 2.5.1, 2.5.2 sdists;
   2.5.1 and 2.1.1 downloaded today); no study release was executed.
4. **Dry run (today, outside the study; `phase_d/dryrun/DRYRUN_RECORD.json`)**: Qiskit 2.3.0 and 2.3.1, five small
   transpiler modules and synthetic hang/crash/long tests; a collect-only of the full 2.3.1 slice (ids only); **all
   eight backport modules executed on 2.3.1** to check importability and inherited-test hiding (D1, D2, D3, D6, D7, D8
   passed; D4 failed for the missing 2.5 feature; D5 could not be imported). This revealed backport durations on
   2.3.1 (for example D6: 0.23 s and 1.62 s; D1: 0.03-0.06 s), which are correlated with, but are not, the study
   costs. The analysis script ran end to end on the dry-run data (`dryrun_analysis_output.json`). Three changes
   followed (normalization of addresses with underscores, a larger calibration workload, backports run warm after
   their logical file); the dry-run data were produced before the last runner change, which was then checked
   separately on 2.3.1.
5. PyPI metadata (upload times, SHA-256 of wheels and sdists).
6. Tests of the analysis on synthetic data (`tests/test_phase_d.py`).

## 11. Handling rules, deviations and invalidation

- An event whose P run, B collect list or all B passes are missing is excluded and reported; the analysis runs on the
  rest (n and minimum p reported).
- If the backported test passes on B in some pass, or fails on F, it is not detecting; if D_e is empty the event is
  undetectable (APFDc 0 and no detection for every policy: a tie) and is reported, not excluded.
- A test whose file fails to collect on B is absent from S_e. Pre-existing failures that also fail on F (environmental)
  are not detecting.
- A missing budget lock, an F-check that could not be run, or imputed real costs are recorded in `deviations`.
- Any change after this record to the files in the first block of `PREREGISTRATION_PHASE_D.sha256`, any use of the
  runner's dry-run options (`--files`, `--data`) for study data, or a run outside the registered environment, is a
  deviation, reported with its reason and, where possible, with results under both versions.

## 12. Order of operations and collection effort

1. **Freeze.** `sha256sum -c PREREGISTRATION_PHASE_D.sha256` passes; `phase_d/data/` does not exist.
2. **Public timestamp.** The user pushes the frozen files; the commit SHA and date are the external timestamp. Nothing
   below happens before the push.
3. **Collection** (sandbox, all with `phase_d/runner/run_phase_d.py`; delete venvs no longer needed, about 290 MB each):
   (a) `prepare` + P timing pass 1 for 2.0.1, 2.0.3, 2.1.2, 2.2.1, 2.4.2; `prepare` + `collect` for the six B releases;
   (b) `assemble`, then `--lock D1 D2 D3 D4 D6 D7 D8`; (c) B passes 1 and 2 for 2.0.2, 2.1.0, 2.2.0rc1, 2.2.2, 2.5.0;
   (d) `assemble` 2.5.0, `--lock D5`, B passes 1 and 2 for 2.5.1; (e) `fcheck` for D1-D8 (F venvs 2.1.1, 2.2.3, 2.5.2
   added); (f) `assemble` every run.
4. **Verification.** `sha256sum -c PREREGISTRATION_PHASE_D.sha256` passes again.
5. **Analysis.** One run: `python phase_d/analysis/phase_d_analysis.py` -> `results/phase_d_confirmatory.json`.
6. **Reporting.** Every quantity of Section 9 with the deviations of Section 11.

**Estimated effort in the sandbox** (calls of at most 150 s; from the dry run and the 2026-10-18 slice timings):
about 200 s per timing pass for 2.0-2.2 (2 calls) and 300-400 s for 2.4.2/2.5.x (3-4 calls, not timed; D7 adds 60 s
per 2.5.0 pass). Prepare/collect about 5 calls, P passes about 12, locks 1, B passes about 32, F checks about 4,
assemble/analysis/verification 2: **about 56 calls (range 45-70), 2.5-3.5 hours**. Nothing needs the user's PC.

## 13. Red team: strongest objections and how this record answers them

| Objection | Answer / remaining limitation |
|---|---|
| "Detection is circular: the detecting test is the fix's test." | Acknowledged (Section 4). Existence and pass/fail are not claimed; the claims are about cost-aware placement and budget fit of a known revealing test, priced as an unseen test. F2 reports pre-existing detection. Limitation: results speak to "a regression test already in the suite", not to fault discovery. |
| "The backported test is new, so the estimator never saw it; the result hinges on the unseen rule." | Intended and realistic; the rule is frozen and simple; three alternative rules are reported exploratorily. Limitation: a different rule could change H1 and D1. |
| "Eight events, two pairs share B: pseudo-replication, no power." | Min-p computed (Section 9.1): n = 8 gives 0.0039, n <= 5 makes H1/H2 unsupportable. Decision rules where tests are underpowered. Cluster sensitivity with 6 clusters reported. Limitation: generalisation beyond these 8 faults is weak. |
| "Pytest file order is not Qiskit's CI order (stestr, parallel workers)." | True; `default` is the order a developer running pytest gets. `file_rr` and `random` are other cost-blind references. Limitation: no claim about Qiskit's actual CI scheduler. |
| "Serial single-thread seconds are not CI seconds." | Budgets and costs are in the same serial seconds, so compliance is internally valid. Limitation: parallel CI wall time and machine noise across sessions (Phase C's concern) are not tested; here P and B run on one machine, which isolates code-change drift. |
| "Charging a subset the sum of per-test durations measured in full-file runs ignores setup and import effects." | Same attribution in P and B; per-file runner overhead reported exploratorily. Limitation: a real subset run could pay class setup on a different test. |
| "The backported test runs in a separate file." | It runs in the same process right after its logical file (warm), and is placed at the end of that file in the CI order; start-of-file placement reported. |
| "D7's cost is the timeout you chose." | 60 s fixed now (pilot value); 10-s sensitivity reported; F3 states the tie by construction at the pr tier. |
| "The pilot already showed the tests fail; you knew the outcome." | Only F1/F2 depend on that and they are forecast checks. No per-test duration of a study release has been seen. |
| "Budgets as a fraction of the estimate let a bad estimator set its own budget." | As in Phase C (rule E); P1 compares real spend with that budget and P2 tests the estimate itself; budgets are locked before B runs. |
| "Selectors were simplified; COAST loses its tier key and severity." | Documented mapping (Section 3); severity and tier have no unit-test meaning. The algorithm is otherwise identical (verified against a literal port of COAST's loop in `tests/test_phase_d.py`). |
| "Wheel pairs bracket whole releases." | Patch releases are small backport sets; the fault-revealing check on F is what defines detection, not commit attribution. D3's B is a release candidate; D2/D6 and D3 cross minor releases. |
| "2.5.x passes are long and the sandbox kills processes." | Runner is resumable at test level; external kill and resumption verified in the dry run. |

## 14. Files of this record

The SHA-256 manifest `PREREGISTRATION_PHASE_D.sha256` lists them. First block (changing any of them after the record
is a deviation): this file, `phase_d/analysis/phase_d_analysis.py`, `phase_d/runner/run_phase_d.py`,
`phase_d/runner/phased_plugin.py`, `phase_d/runner/calibrate.py`, `phase_d/config/phase_d_config.json`,
`phase_d/config/constraints.txt`, `phase_d/events/phase_d_events.json`, `phase_d/backports/test_backport_d1.py` ...
`d8.py`, `phase_d/tools/make_backports.py`, `tests/test_phase_d.py`. Second block (supporting artefacts):
the dry-run record and data, the archived sandbox helpers and prior observations.
