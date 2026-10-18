# Phase D: independent verification and exploratory (post hoc) diagnosis

Date: 2026-10-18. The checker had no part in the data collection. Nothing frozen was modified: `sha256sum -c` still passes after this check, and `phase_d/data/` and `results/phase_d_confirmatory.json` were not touched.

New files (all non-frozen):
- `verification/phase_d_recompute_p1p2.py`: an independent recomputation of P1 and P2. It does not import the analysis script.
- `phase_d/analysis/phase_d_diagnostics.py`: exploratory / post hoc diagnostics.
- `results/phase_d_exploratory_diagnostics.json`: the output of the diagnostics script.

## Part 1: Verification

| # | Check | Result | Evidence |
|---|---|---|---|
| 1a | `sha256sum -c PREREGISTRATION_PHASE_D.sha256` | PASS | All 43 entries OK. |
| 1b | Analysis hash: results file vs frozen vs locks | PASS | `analysis_sha256` = `26bc45bc…2bd62242` in the results file, in the manifest and in all 8 locks. |
| 1c | Lock inputs | PASS | Each lock's `p_run_sha256` and `b_collect_sha256` equal the current files. `budget_lock_matches` = true for all 8 events. All 31 `inputs_sha256` entries in the results match the files. `k_measured` is 0.91–0.98 for every event (inside [0.8, 1.25]), so k = 1. |
| 1d | Locks precede B timing | PASS (with a caveat) | See the timeline below. |
| 2a | Runs complete; test counts vs collect-only | PASS | 17/17 runs have `complete: true`. For every B pass the record set equals the collect-only list exactly (0 missing, 0 extra): 2.0.2 2448, 2.1.0 2539, 2.2.0rc1 2655, 2.2.2 2671, 2.5.0 7670, 2.5.1 7676. |
| 2b | Outcomes per run | PASS | P: 2.0.1 2406 passed / 30 skipped / 2 failed; 2.0.3 2421/30/2; 2.1.2 2495/53/0; 2.2.1 2608/52/0; 2.4.2 7124/53/0. B (pass1; pass2): 2.0.2 2415/30/3 (same); 2.1.0 2481/53/5 (same); 2.2.0rc1 2595/52/8 (pass2 2596/52/7); 2.2.2 2617/52/2 (same); 2.5.0 7611/56/2 plus 1 timeout (same); 2.5.1 7617/56/3 (same). No errors or crashes. The one pass-to-pass difference is the D3 backported test `..._with_allocated_ancilla_2_1` (failed, then passed). The rule correctly leaves it out of D. |
| 2c | Detecting tests fail on B in every pass and pass on F | PASS | D1: 2 tests (`reuse_on_differing_circuits_3_2`, `_4_3`), failed/failed → passed. D2: 1 (`..._initial_layout_set_4_3`). D3: 7. D4: 2. D5: 3. D6: 2. D7: 1 (`test_custom_gate_in_target`, timeout/timeout, i.e. a 60 s hang → passed). D8: 1. All other backported parametrisations pass on B, so they are correctly not counted in D. |
| 3 | Re-run under PYTHONHASHSEED = 0 and 12345 | PASS | Both outputs and the results file share sha256 `eb014317…15ddac7`. They are byte-identical and report no deviations. |
| 4 | Independent P1/P2 recomputation | PASS | Largest absolute difference from the results file across all spend ratios and relative errors is 4.6e-7 (the results file rounds to 6 decimals). P1 cheapest_first: mean 2.7372 / max 4.7466 at 5%, mean 1.4509 / max 2.0728 at 25%. coast_d: mean 2.7374 / max 4.7472 at 5%, same values as cheapest_first at 25%. P2 errors as reported. **P1 FAILED and P2 FAILED both reproduce.** |

**Timeline (UTC, sandbox clock).**
- P passes ran 2026-10-17 20:34:35–20:55:01.
- B collect-only ran 20:55:35–20:57:39.
- Locks D1–D4 and D6–D8 have `locked_utc` 20:57:52. They were pushed in a3c1148 at 2026-10-18 01:22:43.

Earliest B record per release. Times are the minimum of env `utc`, per-test launch time `t`, and file mtime, which all agree.

| Release | Earliest B record | Required after |
|---|---|---|
| 2.0.2 | 01:24:03 | 01:22:43 (margin 80 s) |
| 2.1.0 | 01:33:41 | 01:22:43 |
| 2.2.0rc1 | 01:39:47 | 01:22:43 |
| 2.2.2 | 01:46:04 | 01:22:43 |
| 2.5.0 | 01:52:36 | 01:22:43 |
| 2.5.1 | 05:46:06 | 02:15:45 (D5 lock push 25ad1e3). The D5 lock was written at 02:04:32, after its P run (2.5.0 pass 1, ended 01:58:25). |

F-checks ran at 02:09–02:12 for D1–D4 and D6–D8, and at 05:54:58 for D5. This matches the order note.

Caveat: the mount has no `.git`, so I could not check the commit times myself. They are taken from `collection_notes.md`. The 80 s margin for 2.0.2 assumes that the sandbox clock and GitHub's clock agree to within about a minute.

## Part 2: Exploratory diagnosis (POST HOC, not confirmatory)

### a. Why D2/D6 (2.0.3 → 2.1.0) show +117%

This is not a measurement artefact. The calibration factor was k_measured = 0.94 (k = 1 applied), and B pass1 vs pass2 Spearman = 0.997. The cause is that two files changed drastically between releases:
- **`test_solovay_kitaev.py`**: in 2.0.3, 9 tests cost about 10 s each. The 17 SK tests seen in both releases are estimated at 99.1 s but cost 6.1 s on 2.1.0. This one file contributes +89 s, which is 113% of the net +78.9 s gap.
- **`test_template_matching.py`**: in 2.1.0 all 23 tests are *skipped* (11.1 s → 0.006 s). The skip reason is not recorded.

There is no release-wide speed-up. Leaving out those two files, the 2,353 remaining seen tests are estimated at 35.6 s and cost 39.4 s. Partly offsetting the two files, the 140 unseen tests are priced at 0.37 s but cost 21.8 s (`test_optimize_clifford_t.py`: 10 new tests, 0.02 s estimated vs 12.3 s real). With SK and that file excluded, the error is +4.4%.

Other events:
- D4/D7 (−19%): the new file `test_two_qubit_peephole.py` (250 tests priced at the global median, 0.27 s vs 13.1 s) and `test_unitary_synthesis.py` (0.96 vs 6.0 s). Without them the error is +1.8%.
- D3 (−11%): one seen test, `test_triple_circuit_4_3`, went from 0.82 s to 9.7 s.

### b. Why cost-aware plans overspend (cheapest_first; coast_d is the same to 3 decimals)

**(iii) Unseen tests explain nearly all of it.** Split of the real spend of the 5% plan, as a share of the budget:

| Event | Seen tests | Unseen tests | Unseen real/est |
|---|---|---|---|
| D2/D6 | 0.96 | 2.99 | 30–101× |
| D4/D7 | 0.92 | 3.82 | 40× |
| D3 | 0.91 | 0.44 | |
| D1, D5, D8 (almost no unseen tests) | 1.09, 1.13, 0.93 | | |

Cheap-looking new tests get pulled into the plan first.

**(i) Winner's curse is small.** Seen tests chosen for the 5% plan have real/est between 0.94 and 1.13. Within one release (plan on B pass 1, charge B pass 2) the spend is 0.94–1.02.

**(iv) Noise is small.** Spearman between B pass 1 and pass 2 is 0.94–0.998.

**(ii) Fixed per-test overhead does not bias the estimate.** In the cheapest decile, the median of real − est is ≤ 0.1 ms. Setup and teardown are 3–29% of plan cost, but they are present in both P and B. Wall-clock time per run is 1.6–2.7× the sum of test durations (process start, imports, collection). Neither est nor real includes this time, so it does not affect P1 as defined. A real CI time box would still pay it, and collect-only alone takes 3.3–7.1 s, which is about the size of a 5% budget.

**Post hoc corrections** (the registered budget in seconds is kept fixed; the thresholds are 1.25 for the mean and 2.0 for the max):

| Correction | 5% mean / max | 25% mean / max |
|---|---|---|
| Registered | 2.74 / 4.75 | 1.45 / 2.07 |
| Unseen priced at file/global mean | **1.03 / 1.13** | 1.26 / 1.88 |
| Unseen priced at global P90 | **1.03 / 1.13** | 1.40 / 1.96 |
| Unseen tests in a separate always-run lane | **1.03 / 1.13** | **0.99 / 1.06** |
| Floor at P median | 1.55 / 3.79 | 1.41 / 2.02 |
| Shrink seen tests halfway to file median | 1.81 / 4.02 | 1.62 / 2.18 |
| File-level, unseen at mean | 1.33 / 2.35 | **1.00 / 1.16** |

The lane option meets both thresholds, but the lane itself costs 0.3–5.7× the budget in D2/D6/D3/D4/D7. It moves the problem rather than solving it. All of these corrections are post hoc and would need pre-registration and new events before anyone relies on them.

### c. Heavy tails do not explain the difference

The Phase D suites are as heavy-tailed as the synthetic corpus:

| | Top 1% share | Top 5% share | Gini |
|---|---|---|---|
| Phase D (median over events) | 0.59 | 0.83 | 0.90 |
| Synthetic (median over 19 events) | 0.44 | 0.90 | 0.94 |

So heavy-tailedness is not what separates the two settings. The data point to two other differences:
- **Cold start.** Release-to-release churn adds new, expensive tests that the estimator prices at the median.
- **Scale.** Median test cost is about 2 ms here vs 48 ms in the synthetic corpus. Suites total 65–165 s vs about 1,224 s, so a single mispriced 10 s test is 1.5–3× a 5% budget.

### d. Detecting tests

Every detecting test is file-median-priced. Est vs real, and rank under default / cheapest_first / coast_d (suite size in brackets):

| Event | Est vs real | Rank: default / cheapest_first / coast_d |
|---|---|---|
| D1 | 7.3 ms vs 10.8 ms | 154 / 2064 / 2064 (2671) |
| D2 | 5.9 vs 5.9 ms | 1821 / 1844 / 1845 (2537) |
| D3 | 6.1 vs 3.2 ms | 1674 / 1838 / 1840 (2655) |
| D4 | 1.6 vs 2.1 ms | 695 / 6019 / 6026 (7669) |
| D5 | 4.3 vs 28.5 ms | 559 / 6493 / 6496 (7676) |
| D6 | 0.9 vs 6.4 ms | 2490 / 586 / 610 (2535) |
| D7 | 1.2 ms vs 60 s (hang) | 1734 / 4800 / 4808 (7667) |
| D8 | 1.0 vs 1.1 ms | 837 / 696 / 709 (2448) |

- Detected within 5% budget: coast_d D6, D8; default D1.
- Detected within 25% budget: coast_d D1–D3, D5, D6, D8; default D1, D4, D5, D8. D7 is never detected under either budget.
