# Phase E: independent verification and post hoc diagnosis

Date: 2026-10-19. Scope: `PREREGISTRATION_PHASE_E.md`, `results/phase_e_confirmatory.json` (sha256 `901c543b...52d2`, unchanged by this check).
Scripts: `verification/phase_e_recompute.py` (independent, does not import the analysis script; exit code 0 = all checks pass) and
`phase_e/analysis/phase_e_diagnostics.py` -> `results/phase_e_exploratory_diagnostics.json` (POST HOC, no confirmatory claim).
No frozen file, nothing under `phase_e/data/`, and not the confirmatory results file was modified.

## Part 1: verification (all PASS)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1a | `sha256sum -c PREREGISTRATION_PHASE_E.sha256` | PASS | 49/49 OK |
| 1b | Analysis/config hash in results = frozen | PASS | `c61725ea...fc5a` / `3be149d3...edc` |
| 1c | Lock hashes = `LOCK_PUSHED.json` (commit 8e81ea8) | PASS | 10/10. Each lock records the frozen analysis/config hash and the sha256 of the current P run and B collect file. `inputs_sha256` in the results file matches all 40 assembled files |
| 2a | Every B timing record after the lock commit (22:59:42Z) | PASS | Earliest B record per release (jsonl `t` and file mtimes): 1.0.1 23:00:31, 1.1.0 23:08:33, 1.1.2 23:16:50, 1.2.1 23:25:04, 1.3.0 23:33:07, 1.3.2 23:41:47, 1.4.0 23:50:24, 1.4.2 23:59:04, 1.4.5 00:07:27, 2.4.1 00:17:26 (all UTC). The margin is 49 s for the first release |
| 2b | All P runs and B collects before lock writing (22:49:56-57Z) | PASS | P runs 22:00:20 to 22:44:31 (last record or mtime). Collects 22:45:00 to 22:49:49 |
| 2c | No Phase E measurement before dfc413c (21:59:09Z) | PASS | The earliest study data is 22:00:20Z (P 1.0.0), 71 s after the commit. Contact before registration was limited to PyPI metadata, sdist member names and a pip dry-run resolution (`release_checks.json`, 21:34:26Z), and this is disclosed in Section 10. The dry run used 2.2.3 (a Phase D release) |
| 3 | Completeness | PASS | All 30 runs and 10 collects are complete (COMPLETE markers present, `complete: true`). Both B passes equal the collect-only set exactly (0 missing, 0 extra, 0 duplicates). `n_imputed_real` = 0, there are no deviations and no exclusions. Pass-1 outcomes (failed/passed/skipped): E1 1/2474/25, E2 2/2578/27, E3 2/2584/27, E4 3/2641/31, E5 3/2728/31, E6 3/2742/31, E7 3/2760/31, E8 3/2764/31, E9 4/2821/31, E10 0/7090/53. Pass 2 is identical |
| 4 | Re-run of the frozen analysis to /tmp, PYTHONHASHSEED 0 and 12345 | PASS | Both outputs are byte-identical to the results file (sha256 `901c543b...`) |
| 5 | Independent recomputation (all estimators, pairs, fractions, policies, budgets vs locks) | PASS | 0 differences (tol 5e-6) |

Recomputed decisions (primary):
- P1' is NOT supported. cheapest_first@5% has mean 1.170 and max 2.795 (E2). coast_d@5% has mean 1.139 and max 2.559 (E2). cheapest_first@25% has mean 1.041 and max 1.403 (E2). coast_d@25% has mean 1.037 and max 1.377 (E2). E2 is the only pair above 1.25. E5@25% (1.175/1.162) is the next highest.
- P2' is supported. The median |error| is 3.19% and 10/10 pairs are within ±25%. Errors range from -4.8% (E5) to +6.1% (E2).
- Phase-D-rule comparator: cheapest_first@5% has mean 1.305 and max 3.551, and @25% has mean 1.068 and max 1.605. P2-type accuracy: median 3.35%, 10/10 within the band.

Caveats: all study timestamps come from the sandbox clock (jsonl, env records, mtimes). Only the commit times (GitHub API, unsigned commits, so these are committer-set dates) are external. The GitHub public events feed did not yet list the Phase E pushes at check time (latest event 2026-10-18T02:15:54Z). It is worth re-checking the push-event times later.

## Part 2: post hoc diagnosis of E2 (1.0.2 -> 1.1.0). Exploratory only.

**The new files did not cause the overspend.** E2 has the 3 pre-flagged new files (test_elide_permutations 18 tests, test_remove_final_reset 4, test_star_prerouting 24, so 46 tests). Each is priced at the P99 of 0.300 s, for 13.81 s estimated against 1.45 s real. None of the 46 tests had real cost above its price except 3 of the 24 in test_star_prerouting (max 0.372 s). Because the price is high, cheapest_first selects 0 of them at 5% and 25%. coast_d selects 3 (one per file), which cost 0.0025 of the budget. The over-pricing inflates E2's total (+6.1%) and therefore its budget, which makes the overspend smaller rather than larger.

**Seen tests caused it.** At 5% cheapest_first (budget 5.40 s, real spend 15.10 s), the seen part is 2.702 of the ratio, in-file 0.093 and new-file 0. There are two mechanisms:
1. **A skipped-on-P, run-on-B test.** `test_transpiler.py::TestTranspileMultiChipTarget::test_transpile_does_not_affect_backend_coupling_4_3` was *skipped* on 1.0.2 (priced at 1.8 ms) and *passed* on 1.1.0 at 6.20 s (6.25 s and 6.15 s in the two passes). Its parametrised siblings take 0.6 to 0.8 s. This single test is 1.148x the 5% budget and 0.230x the 25% budget. Without it, the ratios are 1.647 (5% cf), 1.411 (5% coast), 1.173 (25% cf) and 1.148 (25% coast). So at 25% it alone explains the failure. No other pair has any skipped-to-run seen test.
2. **A broad slowdown of cheap seen tests at the minor release.** Excluding the outlier, the 1968 seen tests in the 5% plan cost 1.59x their P duration. The median per-test ratio is 1.73, 69% of tests are above 1.5x, and the median increase is +1.18 ms on a 1.61 ms median. The increase is in the call phase (call 4.55 s on P vs 13.87 s on B, setup 0.51 vs 0.55 s). It is spread across files: test_transpiler 19% of the residual excess, test_preset_passmanagers 15%, then many small contributions. This is not measurement noise: within-B self-selection (plan on pass 1, charge pass 2) gives 1.005. Unselected seen tests cost 0.96x. In the other nine pairs the median per-test ratio of the selected seen tests is 0.86 to 1.09.

**Spend split, primary, cheapest_first (seen / in-file / new-file, as a share of the budget).** 5%: E1 1.009/0.058/0, E2 2.702/0.093/0, E3 1.065/0/0, E4 0.938/0.000/0, E5 1.037/0.013/0, E6 0.990/0/0, E7 1.012/0/0, E8 0.932/0/0, E9 0.849/0.000/0, E10 1.004/0/0. 25%: E5 0.956/0.218/0 (in-file tests 2.99x their file-mean price), E2 1.332/0.070/0, and all others have in-file at most 0.014. Full per-policy detail is in the JSON.

**New files.** Brand-new files appear in 2 of 10 pairs (E2 with 3 files and 46 tests, E5 with 1 file and 8 tests, so 4 files and 54 tests). Both pairs open a minor series. Under the primary rule, coverage of new-file tests is 0% at 5% and 25% for cheapest_first. For coast_d it is 6.5% at E2 (3/46) and 12.5% at E5 (1/8), at both fractions. The Phase-D rule (global median, 2.4 to 4.5 ms) selects 100% of them.

**Primary vs Phase-D rule (cheapest_first 5% / 25%).** E1 1.068/1.070 and 1.025/1.025. E2 2.795/3.551 and 1.403/1.605. E3 1.065/1.138 and 1.061/1.060. E4 0.938/0.938 and 0.960/0.963. E5 1.050/1.528 and 1.175/1.233. E6 0.990/0.988 and 0.973/0.979. E7 1.012/1.014 and 1.001/1.004. E8 0.931/0.931 and 0.928/0.928. E9 0.849/0.885 and 0.903/0.903. E10 1.004/1.004 and 0.980/0.980. The primary rule is never materially worse. It helps exactly where unseen tests exist (E2, E5 and E3). Under the Phase-D rule, cheap-priced new-file tests add 0.31x at E2 and 0.005x at E5, and in-file tests add 0.40x (E2) and 0.55x (E5) at 5%. The primary rule removes most of that, but it cannot remove the seen-test component.
