# Phase C independent verification (2026-10-17)

Verifier: independent agent. No frozen file, label or result was modified. Scratch scripts are in /tmp (v2.py, indep.py, restart.py, r2.py, sens.py, fp.py). The re-runs wrote to /tmp only, with PYTHONDONTWRITEBYTECODE=1.

| # | Check | Result |
|---|---|---|
| 1 | `sha256sum -c PREREGISTRATION_PHASE_C.sha256`: all 28 entries OK. `script_sha256` in results = f2b8ed28...7d30, which matches the frozen hash and the file on disk | PASS |
| 2 | 1,160 raw `result.json` per cohort (10 events x 116 units), 0 parse failures. labels.json n = 1160 with keys identical to the raw files. 0 mismatches in label/oracle_cost_s/cpu_time_s/total_cost_s/fault_id/env, and 0 raw_sha256 mismatches. event_environment_id: C1 = phasec-qiskit-2_4_2 (1160/1160), C2 = phasec-qiskit-2_2_3 (1160/1160). Earliest mtime: C1 2026-10-16T17:20:38Z, C2 2026-10-16T19:57:01Z. 0 files are older than the push (17:17:46Z). Latest: C1 19:56:25Z, C2 2026-10-17T02:30:16Z | PASS |
| 2b | Wrong-Qiskit check. The raw files do not record the Qiskit version, so I used a pass-order fingerprint from the baseline profile: 2.4.2 runs Size before Depth, 2.2.3 runs Depth before Size. All 1160 C1 files carry the 2.4.2 signature and all 1160 C2 files carry the 2.2.3 signature, including the 34 pairs labelled after the restart. Each unit has a single fingerprint across all 10 events in each cohort. The driver also enforces `qiskit_required` | PASS (no mislabelled pair) |
| 3 | Frozen script re-run with `--out /tmp/...` under PYTHONHASHSEED=0 and 12345. Removing the `runtime_s` line, both outputs are byte-identical to results/phase_c_confirmatory.json (sha256 cfed61e7... for all three). P1/P2 True; Holm p H1-H4 = 0.5156/0.5156/0.0430/0.5156, none supported | PASS |
| 4 | Independent P1 (raw files + cost model, no analysis import). k_raw = median of 44 ratios (prev CPU >= 0.05 s) = 0.4479 (C1) / 0.4816 (C2). Both are outside [0.8, 1.25], so k is applied. C1: est 557.53 s vs realised 634.77 s, so -12.17%; median APE over the 8 expensive units 12.67%. C2: 599.50 vs 649.66, so -7.72%; median APE 5.98%. These equal the script's values to 4 decimals and are within ±25% / <=25% | PASS |
| 5 | Independent P2, cheapest_first (greedy ascending by estimated cost, skip-if-over, rule-E x k budgets, charged total_cost_s). C1: pr (29.36 s) mean 0.9865, max 0.9922; nightly (293.58 s) mean 0.8290, max 0.8437. C2: pr (31.57 s) mean 0.8937, max 0.8969; nightly (315.68 s) mean 0.8139, max 0.8350. Exact match with the script | PASS |
| 6 | Deviation (restart). See notes | PASS (no result-changing effect) |
| 7 | AUC / H3 reported below | reported |

## Notes on item 6
- In C2 there is a 14,242 s gap before pair #1127 (wide-drop-opt-loop, qft-n12-line-opt1). Pairs 1-1126 were labelled before the restart and 1127-1160 after it. The 34 post-restart pairs are 4 events of qft-n12-line-opt1 plus all events of qft-n12-line-opt3, rc-n12-line-opt1 and rc-n12-line-opt3. C1 has no gap longer than 268 s.
- Protocol settings held across the whole run: cost_repeats = 5 and warmup = 1 in all 2320 files, 3 baseline + 3 candidate timed runs everywhere, and exactly one distinct baseline cpu_time_s per unit per cohort (the cost cache was reused, including across the restart for qft-n12-line-opt1). Thread pinning is enforced by `_guard`. Running chunk() on one pair at a time does not change the engine call.
- Timing shift. For qft-n12-line-opt1, the C2/C1 oracle-cost ratio is about 1.00 before the restart (n=6) and about 1.06 after it (n=4). For the post-restart-only units the ratio is 1.11 / 1.01 / 0.99. The general C2/C1 baseline-CPU ratio is 1.07 (IQR 1.04-1.12), so this shift is within the normal session-to-session variation.
- Sensitivity of C2 to the post-restart oracle costs, scaled by x:
  - x 0.943: P1 -3.7% / 5.8%
  - x 1.10: P1 -14.1% / 10.1%, P2 nightly 0.857
  - x 1.25: P1 -22.1% / 12.5%, P2 nightly 0.921 (max 0.945)
  - pr spend is unchanged in every case, because no post-restart unit is selected at pr.
  - Both claims hold under every one of these perturbations.

## Item 7 (from results)
Mean realised AUC per cohort (C1 / C2):

| Selector | constant estimator | previous-session estimator |
|---|---|---|
| cheapest_first | 0.7698 / 0.7683 | 0.9923 / 0.9919 |
| diversity_only | 0.8049 / 0.8013 | 0.9923 / 0.9919 |
| composite (proposed) | 0.6601 / 0.6595 | 0.9480 / 0.9475 |
| random | 0.8918 / 0.8921 | 0.8918 / 0.8921 |

COAST (own estimator): 0.9923 / 0.9919.

H3: 9 wins / 1 loss / 0 ties, sign p = 0.0107, Holm p = 0.0430, permutation p = 0.0029. It is not supported because the detection condition fails: at pr, COAST detects 18 events vs 20 for constant-priced diversity_only (forecast: 9 vs 10 per cohort). The non-inferiority and spend conditions hold. Detection-set Jaccard against the forecast is 1.0 for all 20 events. M1 overrun is 22.4x (C1) / 21.3x (C2).

## Observations (not failures)
- P1 depends on the pre-registered speed rule. The labelling machine was about 2x faster than Kaggle (k ≈ 0.45-0.48). Without scaling, the suite error would be about +96% (C1) / +92% (C2). The remaining -12% / -8% error mostly comes from oracle work speeding up less than transpilation.
- At both tiers, cheapest_first, diversity_only and COAST select the same set (pr: everything except the 8 expensive units and 2 qft-n127 opt3 units), so their P2 spend values are identical.
