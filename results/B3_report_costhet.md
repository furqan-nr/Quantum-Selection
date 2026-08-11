# B3 — Selection results (per cohort, never pooled)

Split: `all` · random seeds: 20 · oracle FP rate: 0.0059

### Cohort: `mutation`  (n_events = 9)

**Detection-vs-budget (mean over events):**

| selector | mean AUC | 95% CI (AUC) | recall@20% | mean nTTFR | overhead s |
|---|---|---|---|---|---|
| proposed *(proposed)* | 0.7214 | [0.4389, 0.9444] | 0.6667 | 0.2786 | 0.1469 |
| cheapest_first | 0.8395 | [0.6197, 0.9647] | 0.8889 | 0.1605 | 0.0002 |
| history_only | 0.8395 | [0.6197, 0.9647] | 0.8889 | 0.1605 | 0.0034 |
| change_stage | 0.8395 | [0.6197, 0.9647] | 0.8889 | 0.1605 | 0.0002 |
| diversity_only | 0.8742 | [0.6520, 1.0000] | 0.8889 | 0.1258 | 0.0001 |
| random | 0.8211 | [0.7962, 0.8459] | 0.7500 | 0.1789 | 0.0001 |

**Effect size of `proposed` vs each baseline (metric = AUC):**

| baseline | Cliff's δ | magnitude | A12 |
|---|---|---|---|
| cheapest_first | 0.2469 | small | 0.6235 |
| history_only | 0.2469 | small | 0.6235 |
| change_stage | 0.2469 | small | 0.6235 |
| diversity_only | -0.6420 | large | 0.1790 |
| random | -0.1481 | small | 0.4259 |

**Win / tie / loss (`proposed` vs each baseline):**

| baseline | win | tie | loss |
|---|---|---|---|
| cheapest_first | 6 | 1 | 2 |
| history_only | 6 | 1 | 2 |
| change_stage | 6 | 1 | 2 |
| diversity_only | 1 | 1 | 7 |
| random | 2 | 1 | 6 |
