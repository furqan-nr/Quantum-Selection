# Phase E pre-registration: a new-test-aware cost estimator for budgeted test selection, confirmed on fresh Qiskit release pairs

**Date of record: 2026-10-19** (UTC timestamp and file hashes in `PREREGISTRATION_PHASE_E.sha256`). The record becomes
external only when the user pushes these files to the public repository (GitHub commit timestamp). Until then the
SHA-256 manifest is evidence of content, not of time.

**State of knowledge at the time of record.** No per-test duration, collect-only list or test outcome of any Phase E
study release (Section 3) has been measured or seen. No Phase E study release has been installed, imported or executed.
What HAS been observed is disclosed in full in Section 10: PyPI metadata of the candidate releases, their sdists
(downloaded, SHA-256 verified, member NAMES listed: slice-file counts and the names of files new in B), a pip
dependency resolution (metadata only), and a dry run of the runner on Qiskit 2.2.3 (a Phase D release, not a Phase E
one). **All Phase D data are development data** (Section 4): the estimator was tuned and chosen on them, openly.

---

## 1. Motivation and research question

Phase D (`PREREGISTRATION_PHASE_D.md`, `results/phase_d_confirmatory.json`) refuted both of its confirmatory claims:
cost-aware selection planned with the previous release's per-test durations overspent its real-time budget (P1: mean
2.74 / max 4.75 at 5%, 1.45 / 2.07 at 25%), and the suite-cost estimate missed by more than 25% in four of eight events
(P2). The post hoc diagnosis (`verification/phase_d_independent_check.md`) located the overspend in tests that are new
in B: priced at their file's median P duration, cheap-looking new tests were pulled into the plan first and cost 30 to
100 times their price, while the seen tests alone stayed at 0.91 to 1.13. P2's two large misses came from file-level
changes no estimator built from P can foresee (`test_solovay_kitaev.py` 16 times faster in 2.1.0;
`test_template_matching.py` skipped).

**RQ8.** Does a cost estimator that prices unseen tests conservatively, chosen on Phase D's data, keep cost-aware
budgeted selection within its real-time budget, and estimate the suite cost, on Qiskit release pairs never used before?

Phase E varies exactly one thing relative to Phase D: the price of unseen tests. The selectors (`cheapest_first`,
`coast_d`), the budget rule (b_f = f x estimated suite cost), the measurement (runner, per-test durations, two B
passes), the slice and the speed rule are Phase D's. There are no faults, no backported tests and no detection claims.

## 2. Roles

| Role | What | Claim |
|---|---|---|
| Development data | all Phase D data (6 distinct release pairs, 11 timed releases) | none: used to tune and choose the estimator and to compute the forecast (Section 4, 9) |
| Confirmatory | P1', P2' for the PRIMARY estimator on the 10 fresh pairs (Section 8) | the only claims |
| Registered secondary | the same rules for the SECONDARY estimator | reported, no claim |
| Continuity checks | Phase D's P1 thresholds (mean 1.25 / max 2.0) and Phase D's strict P2 (every pair within 25%) for the primary | reported, no claim |
| Comparator | Phase D's registered estimator (file median / global median) on the fresh pairs | exploratory |
| Registered descriptive | N1 new-test coverage and the always-run-lane cost (Section 8.3) | reported, no claim |

Every quantity of every role is written to `results/phase_e_confirmatory.json` whatever its direction.

## 3. Fresh release pairs

**Rule.** P = the latest final, non-yanked release of the same major version uploaded to PyPI before B (Phase D's rule,
restricted to the major line because 1.4.x and 2.x patches interleave in time). Pairs are disjoint (no release in two
pairs), so one budget-lock push suffices. No release used in Phase D in any role (study: 2.0.1, 2.0.2, 2.0.3, 2.1.0,
2.1.1, 2.1.2, 2.2.0rc1, 2.2.1, 2.2.2, 2.2.3, 2.4.2, 2.5.0, 2.5.1, 2.5.2; dry run: 2.3.0, 2.3.1). 1.2.3 is yanked and is
skipped. Ledger `phase_e/events/phase_e_pairs.json`; upload times and SHA-256 of wheels and sdists in
`phase_e/config/phase_e_config.json`; the rule, disjointness and freshness are checked against a PyPI snapshot
(`phase_e/tools/pypi_release_list.json`) in `tests/test_phase_e.py`.

| Pair | P | B | Kind | Slice files P -> B (sdist names) | Files new in B |
|---|---|---|---|---|---|
| E1 | 1.0.0 | 1.0.1 | patch | 106 -> 106 | none |
| E2 | 1.0.2 | 1.1.0 | minor | 106 -> 109 | test_elide_permutations, test_remove_final_reset, test_star_prerouting |
| E3 | 1.1.1 | 1.1.2 | patch | 109 -> 109 | none |
| E4 | 1.2.0 | 1.2.1 | patch | 110 -> 110 | none |
| E5 | 1.2.4 | 1.3.0 | minor | 110 -> 111 | test_remove_identity_equivalent |
| E6 | 1.3.1 | 1.3.2 | patch | 111 -> 111 | none |
| E7 | 1.3.3 | 1.4.0 | minor | 111 -> 111 | none |
| E8 | 1.4.1 | 1.4.2 | patch | 111 -> 111 | none |
| E9 | 1.4.4 | 1.4.5 | patch | 111 -> 111 | none |
| E10 | 2.4.0 | 2.4.1 | patch | 110 -> 110 | none |

Seven patch pairs and three pairs that open a new minor series (Phase D: three and three). Nine pairs are from the 1.x
line: the claims generalise to Qiskit 1.0 to 2.4, not beyond. All 20 releases have a manylinux x86_64 abi3 wheel that
resolves on Python 3.10 with the Phase E pins, and an sdist (SHA-256 verified) with `test/python/transpiler/` and
`test/python/compiler/` (`phase_e/tools/release_checks.json`).

## 4. Development data and the selection of the estimator

**Development data.** Phase D's six distinct (P, B) pairs: 2.0.1->2.0.2, 2.0.3->2.1.0, 2.1.2->2.2.0rc1, 2.2.1->2.2.2,
2.4.2->2.5.0, 2.5.0->2.5.1. Suite = B's collect-only list without Phase D's backported tests (Phase E has none); real
cost = mean of B's two timing passes; every planned test is charged (no exclusion). Script
`phase_e/dev/select_estimator.py` (reads `phase_d/data/assembled/` only and calls the frozen Phase E analysis functions,
so development numbers are computed exactly as the confirmatory ones), output `phase_e/dev/estimator_selection.json`.

**Candidates** (seen tests always priced at their own P duration; `min_seen` = 3 as in Phase D; "new file" = a file
with fewer than 3 seen tests): F0 Phase D (file median / global median); F1 file mean / global mean; F2 file q-quantile /
global q-quantile, q in {0.75, 0.9, 0.95, 0.99}; F3 file mean / global q-quantile for new files, q in {0.75, 0.9, 0.95,
0.99, 0.999}; F4 file mean / mean of per-file means; F5 c x (file mean / global mean), c in {1.5, 2, 3, 5, 8}; F6
max(file mean, global mean); F7 file mean shrunk to the global mean, kappa in {2, 5, 10, 25}; F8 file q-quantile / mean
of file means, q in {0.75, 0.9, 0.95}; F9 c x Phase D rule, c in {2, 3, 5, 8}; F10 file q-quantile (q in {0.75, 0.9}) /
global P99 for new files. Out of scope by design (reported in Section 13): an always-run lane for new tests and a
planning headroom (plan to h x budget). Both change the selection rule, not the estimate; the lane's cost is reported as
a descriptive quantity.

**Criterion** (lexicographic, smaller is better): (1) the number of failed criteria among the four P1' criteria, P2'
and a utilisation guard (mean spend ratio of `cheapest_first` >= 0.75 at both tiers, against estimators that pass by
leaving the budget unused); (2) P1' risk = max over the four P1' criteria of max(mean / 1.25, max / 1.25); (3) median
|suite-cost error|; (4) number of tuned parameters. Within a family the parameter is tuned by the same criterion on the
training pairs; families are ranked on their leave-one-pair-out (LOPO) held-out rows; the best family is the PRIMARY,
the second best the SECONDARY; both are refitted on all six pairs.

**Result (LOPO ranking, `estimator_selection.json`).** F3 (q = 0.99) first, F10 (q_in = 0.9) second, then F5, F4, F6,
F7, F1, F2, F9, F8, F0. Every held-out pair chose q = 0.99 in F3; q = 0.999 ties on P1' and is worse on P2', so the
optimum is not at the edge of the grid.

**PRIMARY estimator (frozen).** Seen test: its P duration. Unseen test in a file with >= 3 seen tests: the mean P
duration of that file's seen tests. Unseen test in a file with < 3 seen tests: the 99th percentile (type 7) of all P
durations. Rationale: a new test in a known file resembles its file, and the mean (not the median) carries the file's
heavy tail; a test in a never-timed file carries no information, so it is priced as expensive and is not pulled into a
tight plan on a guess. **SECONDARY.** As primary, but an unseen test in a known file is priced at the 90th percentile of
its file.

**Phase D, leave-one-pair-out (held-out values; spend = real cost of the whole plan / budget).**

| Held-out pair | primary cf 5% | cf 25% | coast 5% | coast 25% | suite error | Phase D rule cf 5% / 25% / error |
|---|---|---|---|---|---|---|
| 2.0.1->2.0.2 | 0.93 | 0.94 | 0.93 | 0.94 | +0.02 | 0.93 / 0.94 / +0.01 |
| 2.0.3->2.1.0 | 1.08 | 0.57 | 0.96 | 0.57 | +2.15 | 3.95 / 1.65 / +1.17 |
| 2.1.2->2.2.0rc1 | 0.94 | 0.94 | 0.73 | 0.86 | +0.03 | 1.36 / 1.16 / -0.11 |
| 2.2.1->2.2.2 | 1.09 | 1.01 | 1.09 | 1.01 | +0.02 | 1.09 / 1.01 / +0.02 |
| 2.4.2->2.5.0 | 1.03 | 0.93 | 1.03 | 0.94 | +0.32 | 4.75 / 2.07 / -0.19 |
| 2.5.0->2.5.1 | 1.13 | 1.07 | 1.13 | 1.07 | -0.03 | 1.13 / 1.07 / -0.03 |
| mean / max | 1.03 / 1.13 | 0.91 / 1.07 | 0.98 / 1.12 | 0.90 / 1.07 | median abs 0.03, 4 of 6 within 25% | 2.20 / 4.75; 1.32 / 2.07 |

On development data the primary passes P1' (every pair <= 1.25) and fails P2' (4 of 6 pairs within 25%: the
solovay_kitaev change, and +32% at 2.4.2->2.5.0 where 316 tests of new files are priced at P99). The price of the rule
is coverage: in 2.4.2->2.5.0 only 17 of 316 new-file tests enter the 25% plan (Phase D's rule: all 316; real cost of all
unseen tests = 0.70 x the 25% budget). This is why N1 is registered (Section 8.3).

**What Phase D would have scored under the Phase E rules** (registered estimator): P1' fails (max 4.75). P2' on the 6
distinct pairs: median |e| 0.070, 5 of 6 within 25%: passes; P2' on Phase D's 8 registered events (two pairs counted
twice): median 0.149, 6 of 8 (75%): fails. Phase D's strict P2: fails either way.

## 5. Measurement protocol (Phase D's, adapted)

`phase_e/runner/run_phase_e.py` (copied from `phase_d/runner/run_phase_d.py`; measurement code unchanged), plugin
`phase_e/runner/phasee_plugin.py` and calibration `phase_e/runner/calibrate.py` (identical to Phase D's apart from their
docstrings; asserted by a test). One venv per release (Python 3.10, the release's wheel, `ddt`, `hypothesis`, `pytest`,
third-party packages pinned identically for every release by `phase_e/config/constraints.txt` = Phase D's pins except
`numpy==1.26.4`, because Qiskit 1.0.x requires numpy < 2). Single-thread pinning and `PYTHONHASHSEED=0` as Phase D. Slice:
every `test_*.py` under `test/python/transpiler/` (recursive) and `test/python/compiler/`, minus
`test_unitary_synthesis_plugin.py`. One pytest process per file, sorted order, per-test JSON lines, per-test timeout 60 s
(recorded as 60 s), crash records, chunking (launch limit 115 s, kill 145 s) and resumption. Test identity: Phase D's
normalized node id. Environment record per call (CPU, load, pinned variables, runner hashes, venv freeze hash,
calibration).

| Run | Releases | Passes |
|---|---|---|
| P timing | the 10 P releases | 1 |
| B collect-only | the 10 B releases | 1 (input of the lock and the speed factor) |
| B timing | the 10 B releases | 2 |

**Speed rule** (Phase D's): k = calibration of B's collect call / median calibration of P's run calls; outside [0.8, 1.25]
every estimate and budget of the pair is multiplied by k.

## 6. Estimator, real cost, budgets and the lock

- **est(t)**: the frozen primary (Section 4); the secondary and the Phase D comparator are computed the same way.
- **r(t)**: mean over B's timing passes of setup + call + teardown (timeout = 60 s). A suite test without a B record is
  charged its estimate and counted (`n_imputed_real`, a deviation).
- **Budgets**: b_f = f x sum over the suite of est(t), f = 0.05 and 0.25 (0.50 exploratory), per estimator.
- **Plans**: `cheapest_first` (ascending est, greedy with skip within b_f) and `coast_d` (Phase D's COAST with key = file).
  **Every planned test is charged its real cost.** Nothing is excluded from the spend.
- **Budget lock**: `python phase_e/analysis/phase_e_analysis.py --lock E1 ... E10` writes
  `phase_e/data/budget_lock/<E>.json` (input hashes, suite size, k, environment check, total estimate and budgets of all
  three estimators, analysis and config hashes, UTC). Refused if any B timing data exist (assembled or raw), if the P run
  is incomplete, or if a different lock already exists (never rewritten). Inputs: P's pass 1, B's collect list and the
  calibration of B's collect call; nothing else. The runner refuses every B timing pass unless all ten locks exist AND
  `budget_lock/LOCK_PUSHED.json` (written by `run_phase_e.py confirm-lock-push --commit <SHA>` after the user's push)
  records the publishing commit and the locks still have the recorded hashes.

## 7. Exclusions and handling rules

- **Environment rule (decided at lock time, never from B durations):** a pair is excluded if more than 10% of the slice
  files have no test in B's collect list or no test record in P's run (an environment that cannot import the tests). The
  check is stored in the lock.
- A pair without a P run, B collect list or any B pass is excluded. Every exclusion is reported.
- **At least 8 analysable pairs** are required for a decision; otherwise P1' and P2' are reported as "not decided".
- Failed, skipped or timed-out tests keep their measured cost (a CI job pays it).

## 8. Confirmatory claims, decision rules and descriptive outcomes

Pre-declared decision rules on measured quantities, not significance tests. Each claim is reported separately; neither
is reinterpreted if the other fails. Phase E "confirms the estimator" only if both hold.

### 8.1 P1' (budget compliance in real seconds, per pair)

For the primary estimator, `cheapest_first` and `coast_d`, f = 0.05 and 0.25: **every analysable pair has real spend /
budget <= 1.25** (four criteria, all must hold; mean <= 1.25 follows).

Why stricter than Phase D (mean <= 1.25, single event <= 2.0), argued before any fresh data: (a) a CI time box binds per
job, not on average; Phase D's 2.0 allowance existed because its estimator had a known cold-start risk, which is the risk
Phase E's estimator is designed to remove; (b) under Phase D's thresholds the same selection procedure would pick F2
(q = 0.95) and the forecast would be P1 = 1.00 and P2' = 0.90-0.96
(`estimator_selection_sensitivity_phase_d_p1_thresholds.json`): a test that cannot fail. Phase D's thresholds are kept
as a continuity check (reported, no claim). Phase D development score under P1': fails (4.75); the primary: passes
(max 1.13, LOPO).

### 8.2 P2' (suite-cost estimate)

For the primary estimator, e_p = sum est / sum r - 1 over the pair suite: **median over pairs of |e_p| <= 0.15 AND at
least 80% of analysable pairs have |e_p| <= 0.25.**

Why not Phase D's "every pair": a release-level structural change (a file made 16 times faster, a file skipped) is not
an estimator error and cannot be foreseen from P; with ten pairs and Phase D's rate (1 such change in 6 pairs) the
every-pair rule mainly tests whether such a change occurs (forecast 0.04-0.08 for the primary). The band (25%) is
unchanged; at most two of ten pairs may miss, and the median requires the typical pair to be accurate. Phase D under
this rule: passes on its 6 distinct pairs, fails on its 8 registered events (Section 4). The strict rule is kept as a
continuity check (reported, no claim). The rule is not neutral to the estimator: the primary's P99 price for new files
inflates the estimate where new files appear, which is why P2' is uncertain for it (Section 9).

### 8.3 Registered descriptive outcomes (no claim)

**N1 new-test coverage:** per pair and tier, unseen tests selected by the primary's plans (in-file and new-file
separately) and the real cost of all unseen tests, against the Phase D comparator. **Lane cost:** real cost of all unseen
tests / budget (what an always-run lane would add). Also reported: spend split into seen and unseen tests, spend against
f x real suite cost, per-pass spend, per-test accuracy of seen tests, files new or dropped, k, outcome counts.

## 9. Forecast (prior-predictive, from development data only)

Pair bootstrap, 20,000 simulated studies of 7 patch + 3 minor pairs (`estimator_selection.json`, "forecast"). LOPO pool:
the primary's six held-out rows. Extended pool: every (P, B) pair of releases timed in Phase D within a minor (8 patch-like)
or across one minor (14 minor-like), evaluated with the frozen primary (in-sample for the six selection pairs, hence
optimistic). Smoothed: each drawn pair's real costs multiplied by exp(N(0, tau^2)), tau = 0.052 = robust (MAD) spread of
the seen-test log drift over the six development pairs; "2 tau" mimics a larger era shift (Qiskit 1.x).

| P(claim holds) | pure bootstrap (LOPO / extended) | smoothed tau | smoothed 2 tau |
|---|---|---|---|
| P1' | 1.00 / 1.00 | 0.94 / 0.88 | 0.47 / 0.45 |
| P2' | 0.70 / 0.81 | 0.77 / 0.81 | 0.73 / 0.58 |
| both | 0.70 / 0.81 | 0.73 / 0.72 | 0.35 / 0.25 |
| continuity: Phase D strict P2 | 0.04 / 0.08 | 0.05 / 0.08 | 0.07 / 0.05 |
| Phase D comparator, P1' | 0.00 / 0.00 | 0.00 (extended) | n/a |

**Stated forecast.** P1' is more likely than not but not certain (about 0.9 under the central smoothed model; under 0.5
if 1.x drifts twice as much as Phase D's releases); its risk lies in the seen-test drift of the sub-millisecond tests
that fill the 5% plan (development maximum +13%). P2' is open (0.6-0.8); its risks are seen-test drift and file-level
changes at the three minor pairs, and the P99 price of the three new files of E2. Both: about 0.7 (0.25-0.8). The
structure listed in Section 3 (only four new files, at E2 and E5) is known; it lowers the new-file risk of P1' and
concentrates the new-file risk of P2' in E2.

## 10. Disclosure of pre-registration-time computations

1. **Phase D data** (all, as development data): Phase D's results, diagnostics and the independent check were read;
   the estimator was explored, tuned, chosen and forecast on `phase_d/data/assembled/` (Section 4, 9).
2. **Fresh releases** (`phase_e/tools/check_releases.py`, output `release_checks.json`): PyPI JSON metadata of the
   20 study releases and of 1.1.2 and 1.2.0 (checked as alternates, unused); each sdist downloaded to the scratch cache,
   SHA-256 verified, and its member NAMES listed (slice-file counts, presence of the transpiler/compiler directories and
   of the excluded file); afterwards the names of slice files new in B per pair (Section 3). A
   `pip install --dry-run --report` resolution on Python 3.10 with the Phase E pins (metadata only: nothing installed).
   No fresh release was installed, imported, collected or timed, and no test source was read.
3. **Dry run** (`phase_e/dryrun/DRYRUN_RECORD.json`) on 2.2.3 (a Phase D release): two small files, 17 tests; attempt 1
   recorded nothing because a relative `--data` path was opened from the test tree (fixed: absolute path; archived in
   `phase_e/dryrun/archive_attempt1_relative_data_path/`); attempt 2 complete, resumption checked, refusals checked; the
   analysis ran end to end on the dry-run data (lock refused as designed because P = B there).
4. **Order of design iterations on development data** (all before any fresh measurement): (i) exploratory scripts on
   Phase D data (`phase_e/dev/exploration_2026-10-19/`); (ii) first selection run with Phase D's P1 thresholds and a
   smaller grid: primary F5 (c = 3, grid edge), secondary F2 (q = 0.95), forecast P1 = 1.00, P2' = 0.92-0.96 (near-certain);
   (iii) P1' tightened to per pair <= 1.25 (Section 8.1) and the grids extended (q = 0.99/0.999, c = 5/8, F8 q = 0.95, F9,
   F10) so that no optimum sits at a grid edge; (iv) the smoothed-bootstrap spread first used the SD of the seen-test
   log drift (0.48, dominated by the solovay_kitaev file change already in the pool) and was replaced by the robust MAD
   spread (0.052) with a 2 tau variant. The sensitivity output reproduces what the final grid picks under (ii)'s rule.
5. Tests on synthetic data (`tests/test_phase_e.py`).

## 11. Deviations policy

Any change after this record to a file in the first block of `PREREGISTRATION_PHASE_E.sha256`, any use of the runner's
dry-run options for study data, a run outside the registered environment, a B timing pass before the lock push, or
imputed real costs is a deviation, reported with its reason and, where possible, results under both versions. If the
sandbox cannot run a release (install or import failure), the pair is excluded under Section 7 and reported; no
replacement pair is added after the record.

## 12. Order of operations and collection effort

1. **Freeze.** `sha256sum -c PREREGISTRATION_PHASE_E.sha256` passes; `phase_e/data/` does not exist.
2. **User push 1**: the files of this record. Nothing below happens before it.
3. **P runs**: for each P release: `prepare`, `run --pass 1` (resumed until complete), `assemble`, `cleanup`.
4. **B collect**: for each B release: `prepare`, `collect`, `assemble --collect`, `cleanup --keep-tests` (disk).
5. **Lock**: `phase_e_analysis.py --lock E1 E2 E3 E4 E5 E6 E7 E8 E9 E10`.
6. **User push 2**: `phase_e/data/budget_lock/` and `phase_e/data/assembled/` (the lock inputs). Then
   `run_phase_e.py confirm-lock-push --commit <SHA>`.
7. **B timing**: for each B release: `prepare` (venv again), passes 1 and 2, `assemble`, `cleanup`.
8. **Verification**: `sha256sum -c` passes again; an independent check compares the earliest B record of every pair
   with the push-2 commit time.
9. **Analysis**: one run of `phase_e_analysis.py` -> `results/phase_e_confirmatory.json`; report everything (Section 2).

**Estimated effort** (calls of at most 150 s; from Phase D, where a 2.0-2.2 suite took about 2 calls per pass and
2.4/2.5 suites 3-4): prepare 20 releases plus 10 re-prepares about 12 calls; P passes 22-31; B collects 3; lock and push
record 2; B passes 42-62; assemble, verification and analysis 4. **About 95 calls (85-115), 4-5.5 hours.** Disk: one
venv at a time (about 290 MB).

## 13. Red team (adversarial review before the record) and what changed

| Objection | Answer / change |
|---|---|
| "With the tuned estimator, Phase D's thresholds cannot fail." | Agreed: forecast 1.00. P1' tightened to every pair <= 1.25; Phase D's thresholds kept as a continuity check. P1' remains the less uncertain claim (about 0.9); stated. |
| "P2' was relaxed until Phase D would pass." | Band unchanged; the quantifier changed on principle (Section 8.2). Phase D's 8 registered events still fail P2'; its 6 distinct pairs pass; both stated. For the primary P2' is open (0.6-0.8), and the strict rule is reported. |
| "The estimator passes by not running new tests." | Partly true for tests of never-timed files (P99 price): they rarely enter 5%/25% plans. Spend is never excluded; N1 coverage and the lane cost are registered and the Phase D comparator is reported, so the deferred cost is visible. In-file new tests are priced at the file mean and are selected. |
| "Budgets are a fraction of the estimate, so conservative prices buy bigger budgets." | P2' tests the estimate; spend against f x real suite cost is reported. |
| "Selection and forecast use the same data." | The LOPO pool uses held-out rows; the extended pool is labelled optimistic; smoothed and 2 tau variants added. |
| "Garden of forking paths on development data." | Allowed by design (development data) and disclosed step by step (Section 10, item 4) with the sensitivity file; the fresh data are untouched. |
| "Leakage from the fresh releases." | Only metadata and member names (Section 10, item 2); names are lock-time information anyway; no duration, outcome or collect list exists. The selection script reads only Phase D data. |
| "Grid-edge optimum." | Grids extended; F3's q = 0.99 beats 0.999. |
| "Multiplicity." | Two decision rules, no p-values; secondary, continuity and comparator are labelled and carry no claim. |
| "An environment failure could silently shrink a suite." | Environment exclusion rule fixed at lock time (Section 7); at least 8 pairs needed. |
| "The lock could be skipped or rewritten." | Lock refused with B data, never rewritten; B passes need all locks plus a recorded push commit whose lock hashes still match; the earliest B record is checked against the push time. |
| "1.4.x and 2.x interleave: which P?" | Same-major rule; verified by a test against a PyPI snapshot. |
| "Nine pairs are 1.x." | Stated scope; one 2.x pair; three minor crossings. |
| "Numpy differs from Phase D." | One pin set for all Phase E releases (numpy 1.26.4 forced by Qiskit 1.0.x); P and B of a pair share it; the estimator is relative within a pair. |
| "Always-run lane or headroom would also pass." | They change the selection rule, not the estimate; out of scope for the claims; the lane cost is reported. |

## 14. Files of this record

First block of `PREREGISTRATION_PHASE_E.sha256` (changing any after the record is a deviation): this file,
`phase_e/analysis/phase_e_analysis.py`, `phase_e/runner/run_phase_e.py`, `phase_e/runner/phasee_plugin.py`,
`phase_e/runner/calibrate.py`, `phase_e/config/phase_e_config.json`, `phase_e/config/constraints.txt`,
`phase_e/events/phase_e_pairs.json`, `phase_e/dev/select_estimator.py`, `phase_e/dev/estimator_selection.json`,
`tests/test_phase_e.py`. Second block (supporting): the sensitivity selection output, the exploration scripts, the
release checks and PyPI snapshot, the check tool, and the dry-run record, data, configuration, ledger and analysis
output.
