# Phase C pre-registration: confirmatory study of oracle-cost-aware budgeted test selection for the Qiskit transpiler

**Date of record: 2026-10-16** (UTC timestamp and file hashes in `PREREGISTRATION_PHASE_C.sha256`). The record is
external only once the user pushes these files to the public repository (GitHub commit timestamp) or deposits them
(OSF/Zenodo); until then the SHA-256 manifest is the evidence of content, not of time.

**State of knowledge at the time of record.** No ground-truth label exists for any Phase C event (C1 or C2) in any
Phase C data root, and no selector statistic has been computed on real Phase C labels. What HAS been computed before
this record, and is disclosed in full (Section 9): the development analysis on the two already-labelled cohorts; a
transpilation-only firing sweep of the ten operators on Qiskit 2.4.2 (including the 2Q-count/depth deltas that the
quality rule uses); a termination/output-change sweep on Qiskit 2.2.3 (its change sets equal the 2.4.2 ones); exact-
equivalence checks on 14 units; a timing dry run of the unchanged engine on an EXISTING scale-up event; a **registered
sweep forecast** of every selector comparison (proxy labels from the sweeps, proxy costs from sessions A and B); and a
driver check on one cheap unit in a scratch directory (labels not inspected, deleted). Because the selector outcomes
were forecastable, the confirmatory claims are restricted to the quantities no computation has observed: the costs of
the new labeling sessions (Section 8.1).

---

## 1. Motivation

The manuscript (`paper/sqj/main.tex`) found that the pre-specified comparison, in which the transparent multiplicative
`risk_score` selector ("composite") lost to diversity-only and cheapest-first ordering on mutation events, was mostly
driven by MISPRICED ORACLE COST. Selectors priced oracles with constants of at most 0.2 s
(`src/cart/selectors/cost_model.py`), but the exact unitary checks of the eight 12-qubit line units take 25-285 s each
and are ~95% of the real suite cost. With costs taken from other events of the same cohort (near-perfect knowledge),
all simple orders converged, the composite's gap to diversity-only shrank from 0.112 to 0.013 AUC (19 events), the
remainder was mostly the severity term, and constant-priced selections overran the frozen pr budget 51-219 times while
cost-estimated ones stayed at about 1.0 times. All of that was post hoc and used a cross-event estimate that is not a
deployable forecast. Phase C examines, on NEW events and a SECOND SDK version, (i) whether the cost confound replicates,
(ii) whether a DEPLOYABLE estimator (costs measured in earlier sessions) removes it, (iii) whether a simple method built
on that finding (COAST) holds up, and (iv) whether the residual is the severity term. Because (i)-(iv) could be
forecast from transpilation-only sweeps before labeling (Section 8), they are registered forecast checks; the
CONFIRMATORY claims are that the deployable estimate transfers to new sessions and SDK versions (P1) and that budgeted
selection with it respects the budgets in real time (P2).

## 2. Development data vs confirmation data

| | Development (already labelled; used to design Phase C) | Confirmation (not yet labelled) |
|---|---|---|
| Events | primary cohort `data/` (session A, 9 events), scale-up `data_scaleup/` (session B, 19 events) | C1 `data_phase_c1/` (10 events, Qiskit 2.4.2), C2 `data_phase_c2/` (10 events, Qiskit 2.2.3) |
| Role | estimator design, COAST design, budget rule, hypothesis feasibility (`results/phase_c_dev.json`, exploratory) | confirmatory P1/P2; registered forecast checks H1-H4 (Section 8) |
| Previous-session data for the estimator | A->B and B->A out-of-session checks | sessions A and B pooled (frozen in `configs/phase_c_cost_model.json`) |

No Phase C label or Phase C cost feeds any design choice (the transpilation sweeps were used to validate operators;
their forecast was used only to decide which claims can be confirmatory, Section 8). Sessions A and B are used in Phase C ONLY as "previous sessions".

## 3. Corpus

The same 116 cost-heterogeneous units as both earlier cohorts (`manifest_static.json`, byte-identical in `data/`,
`data_scaleup/`, `data_phase_c1/`, `data_phase_c2/`): families ghz, qaoa_linear, qft, random_clifford; widths 5-127;
line and heavy-hex maps; optimization levels 1 and 3; basis {cx, rz, sx, x}; seed 1234. Exact unitary oracle on the
24 line units with n <= 12 (heavy-hex maps add ancillas), structural oracle on the other 92.

## 4. Events

Ten new operators (`src/cart/events/mutations_phase_c.py`) address the "coarse mutants" weakness: each fault is
reachable only for some inputs (width threshold, one topology, one gate type, one routing or translation decision),
and five of ten break semantics or structure, so the exact or structural oracle must do work only it can do. Event
ledgers: `scripts/build_phase_c_events.py` (C1 ids `mutc1-*`, C2 ids `mutc2-*`, same ten families).

| # | Family | Fault type | Mechanism (input gate) | Which oracle can expose it | 2.4.2: outputs changed / quality rule / structurally invalid (of 116) | 2.2.3: changed, errors |
|---|---|---|---|---|---|---|
| 1 | wide_drop_opt_loop | quality | optimization loop skipped, n >= 27 | quality rule | 30 / 15 / 0 | 30, 0 |
| 2 | heavy_hex_trivial_layout | quality | trivial layout, heavy-hex maps only | quality rule | 58 / 55 / 0 | 58, 0 |
| 3 | small_drop_opt_loop | quality | optimization loop skipped, n <= 12 | quality rule | 24 / 12 / 0 | 24, 0 |
| 4 | cp_swap_detour | quality | first CP emitted as SWAP.CP.SWAP (+6 CX, exact) | quality rule | 36 / 2 / 0 | 36, 0 |
| 5 | wide_no_elide_permutations | quality | ElidePermutations skipped, n >= 18 (opt 3) | quality rule | 18 / 8 / 0 | 18, 0 |
| 6 | cp_small_angle_sign_flip | semantic | CP(theta), abs(theta) <= pi/8, emitted as CP(-theta) | exact unitary (qft, line, n <= 12) | 36 / 0 / 0; non-equivalent on qft-n5-line opt1 and opt3 | 36, 0 |
| 7 | wide_rz_sign_flip | semantic | first non-trivial RZ negated after optimization, n >= 10 | exact unitary (n = 12 line units only) | 84 / 0 / 0; non-equivalent on ghz-n12-line-opt1 | 84, 0 |
| 8 | drop_routed_swap | semantic | first SWAP of the routed circuit dropped before translation | exact unitary (qft, random_clifford, line, n <= 12) | 64 / 0 / 0; non-equivalent on qft-n5-line-opt1, random_clifford-n5-line-opt3 | 64, 0 |
| 9 | drop_first_rzz | semantic | first RZZ dropped in translation | exact unitary (qaoa, line, n <= 12) | 28 / 0 / 0; non-equivalent on qaoa-n5-line opt1 and opt3 | 28, 0 |
| 10 | wide_leaky_basis_h | functional | 'h' accepted as native, n >= 40 (out-of-basis output) | structural oracle | 36 / 0 / 36 | 36, 0 |

Forecast detection fractions (proxy rule of Section 8, identical for C1 and C2): operators 1-10 detected by
15, 55, 12, 2, 8, 6, 8, 12, 6 and 36 of 116 units (2-47%); no operator is detected by every unit or by none, so
ordering matters for every event. Semantic operators are detectable only by exact-tier units, and for
`wide_rz_sign_flip` only by the eight expensive 12-qubit exact checks.

All ten terminate on all 116 units under both versions (max single transpilation 5.4 s / 5.7 s CPU). Where a
quality operator fires on an exact-oracle unit it was checked to stay unitarily exact (cp_swap_detour on qft-n5-line-opt1,
small_drop_opt_loop on random_clifford-n5-line-opt1). The other three quality operators fire only on heavy-hex or
>= 18-qubit units, where no exact check is possible; their mechanisms (layout choice, a skipped optimization loop, a
skipped permutation elision) are semantics-preserving within the preset pipeline, and the structural oracle found no
invalid output. Width- and topology-gated operators leave the other inputs' output identical (unit tests). Dropped before this record (disclosed): VF2PostLayout removal on heavy-hex
maps (crashed the opt-3 pipeline: a functional, not quality, fault), 'basic' routing on wide line inputs (0.5-1M
two-qubit gates and > 2.3 GB RAM on qft-n100/n127), DenseLayout on wide line inputs (changed 18 outputs but never crossed
the quality thresholds, i.e. unobservable by construction).

Detection is read exactly as before: a unit detects an event iff its label equals `LABEL_FOR_FAULT[fault_type]`
(quality_regression, semantic_fail, functional_fail). The labeling engine, oracles and thresholds are unchanged.

## 5. Labeling protocol

Identical to the scale-up (`KAGGLE_CALIBRATION.md`): the unchanged engine `cart.labels.ground_truth`, 116 units, all
events, `--cost-repeats 5` (median of 5 clean `process_time` runs after 1 warm-up, measured once per unit and reused
across events), 3 timed baseline and 3 timed candidate runs, write-once raw artifacts, single-thread pinning
(`RAYON_NUM_THREADS=OMP_NUM_THREADS=1`). Driver: `scripts/run_phase_c_ground_truth.py` (adds only the Phase C operator
lookup, a Qiskit-version guard, and a resumable chunk/assemble mode producing byte-compatible `labels.json` /
`profiles.json`). Default machine: a Kaggle CPU-only session (same class as sessions A and B), C1 under Qiskit 2.4.2 and
C2 under Qiskit 2.2.3 (`environment/phase_c/`), one cohort per session. The machine's CPU string and Python version are
recorded. Expected wall time: ~4.7 h per cohort on Kaggle (~2.5 h per cohort on the development sandbox). In the
development sandbox (foreground calls of at most ~9 min, no background processes) the chunk mode is used with unit
slices of at most ~8 min estimated work; the four most expensive units (qft and random_clifford, n = 12, line; about
2-2.5 min per event there) are run three events per call via `--event-ids`. Chunking changes nothing in the engine.

## 6. Cost models and budgets (frozen in `configs/phase_c_cost_model.json` before any Phase C label)

What selectors SEE (each selection is CHARGED the labelled `total_cost_s` = baseline CPU transpilation cost + oracle cost):

- **constant**: the frozen context, baseline profile CPU cost + `ORACLE_COST_EST` (0.05 / 0.20 / 0.05 / 0.01 s).
- **previous-session (deployable, primary)**: baseline profile CPU cost of the Phase C session + the unit's mean labelled
  `oracle_cost_s` in sessions A and B (unweighted mean of the two per-session means). Injected exactly (baseline costs
  = estimate, `ORACLE_COST_EST` set to 0 in memory, as `revision_costscale.py`'s `*_exact` models).
- **analytic (deployable, secondary)**: same transpilation part + `AnalyticOracleModel` fitted on sessions A+B only:
  exact tier c = 0.002442 + 4.2477e-8 * G * 4^n; structural tier c = 0.000168 + 6.3143e-6 * G (G = baseline transpiled
  size, n = width; tier predicted from the manifest and coupling-map size; fitting rule in `coast.fit_analytic`).
- **Machine-speed rule**: k = median over units with previous CPU cost >= 0.05 s of (Phase C baseline CPU cost /
  previous-session CPU cost). The Phase C baseline CPU cost is the engine's calibrated BASELINE transpilation cost
  (unmutated circuit, median of 5, measured per unit before that unit's oracles run and independent of the fault);
  k never uses oracle costs or labels of a Phase C event. The band, the threshold and the previous-session CPU costs
  are frozen in `configs/phase_c_cost_model.json` / `coast.speed_factor`. If k is outside [0.8, 1.25], previous-session and analytic oracle estimates AND both budget
  rules are multiplied by k (`coast.speed_factor`). Sessions B/A gave k = 0.90 (inside the band, no scaling).

Budgets (seconds), frozen now from sessions A and B only:

| Rule | Full-suite basis | pr (5%) | nightly (50%) |
|---|---|---|---|
| **E (primary)** | estimated full-suite cost = sum over units of mean(cpu_time_s + oracle_cost_s) = 1310.897 s | **65.545 s** | **655.449 s** |
| T (secondary, comparability) | transpilation-only suite = sum of mean cpu_time_s = 66.169 s | 3.308 s | 33.084 s |

Each selector receives the budget in seconds and selects within it as measured by its own cost model; the selection is
then charged its labelled seconds.

## 7. Selectors

Baselines `random` (100 seeds for AUC, 20 for budgets), `cheapest_first`, `diversity_only`, `history_only`,
`change_stage`; `decomposed`; the composite `proposed` (default parameters, reserve 0.15); `proposed` without severity
(`ablate=("impact_prior",)`); and **COAST** (`src/cart/selectors/coast.py`, registry `registry_phase_c.py`):
diversity-first greedy coverage of (family, backend, predicted oracle tier), cheaper (estimated) first, severity only
as a tie-break, budgeted by the same estimate; its estimator is the previous-session estimator with the analytic model
as fallback for unseen units. COAST always runs with its own estimator; every other selector is evaluated under all three
cost models. COAST's design was fixed on development data only; it is not tuned after this record.

## 8. Metrics, roles of the analyses, hypotheses and decision rules

*Revised before the freeze after an adversarial (red-team) review; Section 9 lists what was changed and why.*

**Why the selector comparisons are not confirmatory.** Phase C detection labels are deterministic functions of
transpiler output, and the transpilation-only sweeps (Section 9) recorded that output for every operator x unit pair:
the 2.4.2 sweep includes the quality-rule flag and structural validity, and the 2.2.3 sweep's per-unit output-change
sets are IDENTICAL to the 2.4.2 ones for all 1160 pairs. Combined with the per-unit costs of sessions A and B, this
predicts every selector comparison before labeling. We computed that prediction (the **registered sweep forecast**,
`environment/phase_c/verification/sweep_forecast.json`, produced by `environment/phase_c/sweep_forecast.py` with the
frozen analysis script) and found it insensitive to the cost source (session A only, B only, or pooled: identical
signs for H1, H3, H4; H2 6/1/3 vs 5/1/4). Making C2 the primary cohort would not help (its detection sets are as
predictable), and treating C1 and C2 as 20 independent events would be pseudo-replication (same operators, same
change sets). The selector comparisons H1-H4 are therefore kept, computed exactly as designed, and reported next to
their forecast, but **no confirmatory claim is made from them**, whatever their outcome. This decision does not
depend on the direction of the forecast.

**What remains genuinely unknown, and is confirmatory.** The per-unit costs (above all the oracle costs, measured on
the MUTATED candidate circuits) of the two new labeling sessions: a new machine for C1, and a new machine plus a new
Qiskit version for C2. No pre-registration-time computation ran an oracle on a Phase C event (except the disclosed
10-pair driver check, Section 9, whose values were not used). These costs decide whether the deployable estimator and
budgeted selection work, which is the operational claim of RQ4.

**Metrics.** Prioritization AUC (detection vs labelled budget fraction; `cart.metrics.curves.event_metrics`; 0 if never
detected), compared at 4 decimals. Finite-budget: detected (0/1), real seconds / budget, units selected. Cost-estimate
accuracy: estimated vs realised per-unit oracle cost, where realised = the unit's mean labelled `oracle_cost_s` over
the cohort's 10 events and the estimate is the frozen previous-session estimate after the speed rule (Section 6).
Expensive units are fixed now: the 8 units whose frozen previous-session oracle estimate is >= 10 s (the 12-qubit
line units of ghz, qaoa_linear, qft and random_clifford at opt 1 and 3).

### 8.1 Confirmatory family (the only confirmatory claims)

Each P is evaluated in EVERY labelled cohort and is **supported iff every criterion holds in every labelled cohort**;
otherwise it is **refuted** and the failed criteria and cohorts are reported. These are pre-declared decision rules on
measured quantities, not significance tests (no sampling unit is resampled; minimum achievable p: not applicable). The
conjunction over cohorts makes each P harder, not easier, to support, so no multiplicity correction is applied.

- **P1 (cost-estimate transfer).** Under the frozen previous-session estimator, in each cohort:
  (a) |estimated suite oracle cost / realised suite oracle cost - 1| <= 0.25, and
  (b) median absolute percentage error over the 8 expensive units <= 0.25.
  Development reference (out of session): (a) 4.1% / -4.0%, (b) 6.9% / 6.2%. Why it can fail: Kaggle CPU classes vary
  and a speed difference inside the [0.8, 1.25] band is NOT corrected by design; oracle cost of mutated candidates can
  differ from that of the development mutants; C2 uses another Qiskit version.
- **P2 (budget compliance of deployable selection).** With rule-E budgets and the previous-session estimate, in each
  cohort, at the pr AND the nightly tier, for COAST (own estimator), cheapest_first and diversity_only (previous-session
  model): mean real spend / budget <= 1.25 AND no single event > 2.0. Development reference: mean 0.91 (pr) / 0.71
  (nightly), max 0.99. Why it can fail: the pr budget (65.5 s) admits at most one or two expensive units, so a 25%
  cost error on a selected 12-qubit exact check moves the spend by a large factor.

Refutation of P1 with P2 supported (or vice versa) is reported as such; neither is reinterpreted.

### 8.2 Registered forecast checks (not confirmatory; reported in full with the forecast)

Unit of analysis: the OPERATOR (10); per-operator value = mean over C1 and C2 of the per-event value. Statistic: the
one-sided exact binomial sign test on the per-operator differences (ties dropped), Holm over H1-H4 at familywise
alpha = 0.05; secondary statistic: the exact one-sided sign-flip permutation test of the mean. "Supported" = Holm p
< 0.05 AND every listed condition holds. Mechanism checks are no longer conditions (see 8.3).

| | Statistic d (per operator) | Conditions | Registered forecast (W/L/T, sign p, Holm p, supported?) |
|---|---|---|---|
| H1 cost confound | AUC(diversity_only, constant) - AUC(composite, constant) | mean d > 0 in C1 and in C2 | 7/3/0, 0.172, 0.344, no |
| H2 estimator helps the composite | AUC(composite, previous) - AUC(composite, constant) | pooled gap g = AUC(diversity) - AUC(composite) > 0 under constant prices and shrinks >= 50% under the previous estimator | 6/1/3, 0.0625, 0.188, no |
| H3 COAST vs composite as deployed | AUC(COAST, own) - AUC(composite, constant) | non-inferior to the best baseline under the previous estimator (margin 0.01); within rule-E budgets COAST detects at least as many events as constant-priced diversity_only at pr and nightly (pooled counts); COAST spend <= 1.25 at both tiers in both cohorts | 9/1/0, 0.0107, 0.043, no (pr detection 9 vs 10 per cohort: `wide_rz_sign_flip`) |
| H4 severity residual | AUC(composite w/o severity, previous) - AUC(composite, previous) | none | 7/3/0, 0.172, 0.344, no |

Power (minimum achievable p). With k informative (non-tied) operators the smallest one-sided sign-test p is 2^-k;
with all 10 informative it is 2^-10 = 0.00098 (one loss: 0.0107). Under Holm the first-ranked test needs p < 0.0125
(k >= 7 with no loss), the second p < 0.0167 (k >= 6), the third p < 0.025 (k >= 6), the fourth p < 0.05 (k >= 5).
Forecast informative operators: H1 10, H2 7, H3 10, H4 10; so all four are feasible in principle, but H4's
differences are small (|d| <= 0.045) and depend on the fourth decimal. For each H the output reports the realised
result, the forecast, per-operator agreement, and the per-event Jaccard of realised vs forecast detection sets.
Language in the paper: "consistent / not consistent with the registered forecast"; never "confirmed".

### 8.3 Mechanism checks (near-certain by construction; never counted as evidence)

M1: with constant prices, mean real spend / rule-E pr budget > 10 for cheapest_first and diversity_only in each
cohort (forecast 19.9x; holds as long as minute-long exact checks are priced at 0.05 s). M2: shrinkage of the
composite-diversity gap (part of H2's conditions, reported separately).

### 8.4 Computation and handling rules

All statistics are computed by the frozen `scripts/phase_c_analysis.py`, which writes
`results/phase_c_confirmatory.json`:
`python scripts/phase_c_analysis.py --cohort C1=data_phase_c1 --cohort C2=data_phase_c2 --prev data --prev data_scaleup`
It asserts that the estimator and budgets rebuilt from sessions A and B equal `configs/phase_c_cost_model.json`, and
records two leakage checks per cohort: the number of label rows usable as "history" (must be 0: all events of a cohort
share one date) and the source of the speed factor. Deterministic: fixed random seeds (100 for AUC, 20 for budgets),
deterministic COAST, and order-independent summation (verified identical output under two `PYTHONHASHSEED` values).
Undetectable events (no detecting unit) have AUC 0 for every selector, i.e. a tie, dropped from the sign test and kept
in means. Ties are differences of r4-rounded AUCs equal to 0. A missing cohort: the analysis runs on the other alone
(operator = event), `deviation_missing_cohort` is set, P1/P2 are evaluated on that cohort only, and the cross-SDK part
of P1 is not claimed. **ALL results are reported regardless of outcome**: P1, P2, H1-H4 with their forecasts, the
mechanism checks, the secondary statistics, and every exploratory number in Section 10.

**Development data** (`results/phase_c_dev.json`, same code path; the H rows were computed with the pre-review
conditions, which differ only by the two mechanism conditions now moved to 8.3; both held there):

| | A -> B (19 events) | B -> A (9 events) |
|---|---|---|
| H1 | 14 / 3 / 2 (wins / losses / ties), p = 0.006; overrun 19.0x | 7 / 1 / 1, p = 0.035; overrun 20.6x |
| H2 | 7 / 0 / 12, p = 0.008; shrinkage 88%; spend 0.91x | 3 / 0 / 6, p = 0.125; shrinkage 90%; spend 0.91x |
| H3 | 17 / 0 / 2, p < 0.001; 17 vs 17 faults at pr and nightly; spend 0.91x / 0.71x | 8 / 0 / 1, p = 0.004 |
| H4 | 14 / 3 / 2, p = 0.006 | 5 / 3 / 1, p = 0.36 |
| P1 (a) / (b) | 4.1% / 6.9% | -4.0% / 6.2% |
| P2 max mean spend | 0.91 (pr), 0.71 (nightly) | 0.91 (pr) |

**Pre-declared predictions and risks.** (a) H3's pr-tier detection condition fails in the forecast because
`wide_rz_sign_flip` is observable only by the eight 12-qubit exact checks, none of which fits a 5% budget under an
accurate estimator, while constant-priced diversity_only spends ~20x the budget and runs them. This is a real
trade-off (budget-correct selection gives up faults only expensive oracles see) and is reported as such. (b) The
forecast differs sharply from development (where all four H held, A -> B): the Phase C operators are input-gated, and
three wide-only operators (`wide_drop_opt_loop`, `wide_no_elide_permutations`, `wide_leaky_basis_h`) favour the
composite under constant prices. (c) Real labels can depart from the forecast where the proxy rule is approximate:
semantic detection on exact units (only 7 non-equivalence checks were run), quality flags under 2.2.3 (not computed),
and AUC differences at the fourth decimal.

## 9. Disclosure of pre-registration-time computations

- Development analysis on `data/` and `data_scaleup/` (exploratory): `scripts/phase_c_dev.py` -> `results/phase_c_dev.json`.
- Firing sweep, Qiskit 2.4.2, all ten operators x 116 units, transpilation only: output changed, quality-rule flag with
  2Q/depth deltas, structural validity, CPU time (`environment/phase_c/verification/firing_sweep_qiskit_2_4_2.jsonl`).
  This sweep largely determines which units carry `quality_regression` (operators 1-5) and `functional_fail`
  (operator 10) labels, and, with the predicted oracle tier, `semantic_fail` labels (operators 6-9).
- Compatibility sweep, Qiskit 2.2.3: termination and output change per operator x unit; no quality rule, no oracle
  (`compat_sweep_qiskit_2_2_3.jsonl`). Its output-change sets equal the 2.4.2 ones for all 1160 pairs, so C2's
  detection sets are NOT unobserved in any useful sense (an earlier draft of this record said they were).
- Exact-equivalence checks on 13 five/eight-qubit units and ghz-n12-line-opt1 (Qiskit 2.4.2), `equivalence_checks_qiskit_2_4_2.jsonl`.
- Timing dry run of the unchanged engine on two units of the existing scale-up event `mut2-seed-drift-01` under both
  versions, output in /tmp only (`timing_dry_run.jsonl`).
- Dry runs of `scripts/phase_c_analysis.py` on development data (output in /tmp only); results equal the A -> B column.
- **Red-team review (2026-10-16, before the freeze).** It (i) computed the registered sweep forecast (Section 8; proxy
  labels from the sweep, proxy costs = pooled A/B means, frozen analysis script; sensitivity with A-only and B-only
  costs); (ii) on that basis moved H1-H4 from confirmatory to registered forecast checks and introduced P1/P2 on the
  quantities the forecast cannot know; the H statistics, tests and Holm family are unchanged, and the only change to
  their conditions is the removal of two mechanism checks (H1's > 10x overrun, now M1; H2's <= 1.25x spend, now part
  of P2); (iii) made the cost-model build order-independent (`coast.estimator_from_sessions` iterates units in sorted
  order; the frozen cost model is unchanged to 9 decimals); (iv) ran the labeling driver once on a scratch copy in /tmp
  for ONE cheap unit (ghz-n5-line-opt1) x the ten C1 events to confirm it works and to time it (wall time < 1 s per
  call). Those 10 records were inspected only for their schema, cost fields and oracle tier (exact), never for their
  label, and were deleted; they are not part of any Phase C dataset.

## 10. Exploratory (pre-declared, no confirmatory claim)

Rule-T budgets; the analytic estimator (accuracy and all selector outcomes); COAST without the tier key; random;
history_only and change_stage; per-cohort event-level tests; further cost-estimator accuracy (MAPE over all 116 units,
Spearman, the constant model's error, the measured speed ratio k); the subset of informative operators; first-detection
ranks; any comparison between C1 and C2 (SDK-version effects); agreement of realised labels with the sweep forecast.

## 11. Deviations and invalidation

Any change to `mutations_phase_c.py`, `coast.py`, `registry_phase_c.py`, `phase_c_analysis.py`,
`build_phase_c_events.py`, `run_phase_c_ground_truth.py`, `configs/phase_c_cost_model.json`,
`environment/phase_c/sweep_forecast.py` or `sweep_forecast.json` after this record is a deviation and will be reported
with its reason and with results under both versions. A labeling failure of a unit or event (crash of the engine
itself, not a functional_fail label) is reported; the affected event is analysed with the remaining units only if the
engine failure is unrelated to the fault, otherwise excluded and reported. If a cohort cannot be labelled at all, the
other cohort is analysed alone (operator = event) and the deviation is reported. Labeling on a machine outside the
Kaggle CPU class is not a deviation (the speed rule covers it) but the machine is reported.

## 12. Development results in brief (exploratory)

- Previous-session estimator, out of session: oracle MAPE 7.3% (A -> B) and 7.9% (B -> A) over 116 units, 6.9% / 6.2%
  on the eight expensive units (Spearman 0.95); total-cost MAPE 1.7%. Analytic estimator: MAPE 32% / 34% over all units,
  70% / 61% on the expensive units (overestimates them 1.5-1.7x; Spearman 0.90 / 0.92). Constant prices underestimate the
  expensive units ~1000x.
- AUC (A -> B): constant composite 0.768 vs diversity 0.880; previous-session composite 0.882, without severity 0.890,
  cheapest / diversity / decomposed / COAST 0.895 (ceiling = 17/19); analytic: identical to previous for the simple
  orders, composite 0.8815. B -> A: gap 0.153 (constant) -> 0.015 (previous) -> 0.015 (analytic).
- Rule-E budgets (A -> B): constant-priced cheapest/diversity spend 19.0x pr (max 25.8x); previous-session 0.91x
  (max 0.99x) with 17/19 faults; COAST the same; analytic 0.91x. With the manuscript's own frozen pr budget (3.16 s) the
  previous-session estimator spends 1.00x (max 1.05x) versus 51x with constant prices, still 17/19.
- COAST with and without the tier key are identical on development data (the tier key's rationale concerns semantic
  faults, which the development cohorts do not contain).

## 13. Order of operations

1. **Freeze.** All files listed in `PREREGISTRATION_PHASE_C.sha256` are final; `sha256sum -c PREREGISTRATION_PHASE_C.sha256`
   passes. No Phase C label exists in `data_phase_c1/` or `data_phase_c2/` (only `events/` and `manifest_static/`).
2. **Public timestamp.** The frozen files are pushed to the public repository; the commit SHA and date are the
   external timestamp (optionally also an OSF/Zenodo deposit). Nothing is labelled before this push.
3. **Labeling.** C1 under Qiskit 2.4.2, then C2 under Qiskit 2.2.3 (`environment/phase_c/`), with
   `scripts/run_phase_c_ground_truth.py` (full run or chunks followed by `--assemble`). The machine's CPU string and
   Python version are recorded.
4. **Verification.** `sha256sum -c PREREGISTRATION_PHASE_C.sha256` is re-run and must pass.
5. **Analysis.** One run of the command in Section 8.4, writing `results/phase_c_confirmatory.json`.
6. **Reporting.** Every quantity in Sections 8 and 10, whatever its direction, with any deviation (Section 11).
