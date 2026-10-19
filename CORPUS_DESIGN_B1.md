# B1 — Cost-Heterogeneous Corpus Design (the fix for the null)

Written 2026-08-04 (design step B1 of the study plan). This note gives the design rationale for the corpus: the
selection null is not a selector weakness, it is a **corpus** artefact, and this note shows why — with
measured data — and specifies the corpus that removes it. Pre-declared **before** any held-out detection
outcome, per the leakage-safety rule.

---

## 1. Why the null exists (empirically, not by assumption)

The pilot returned a null (all selectors tie: diversity 0.886, classical 0.877, random 0.783, risk_score
0.692) for two coupled, measurable reasons.

**(a) The budget never binds.** The evaluated corpus is 32 units at n ∈ {5, 8}. Measured baseline cost
(`data/profile_baseline/profiles.json`): 207 of 288 profiles round to **0.0 s**, the nonzero ones sit at
0.016–0.25 s, and the whole evaluated suite costs on the order of **~0.3 CPU-seconds**. The tightest CI
budget is the **pr tier at 120 s** (`configs/budgets.yaml`). So the budget is ~**400× looser** than the
suite it is supposed to ration. When every test fits hundreds of times over, there is nothing to select —
every selector "chooses everything," so ordering is the only signal and all methods converge.

**(b) Detection saturates.** At n ≤ 8 on small maps, every mutation is caught by essentially every unit,
so detection-vs-budget AUC has no spread to explain. This is the same regime problem the forward-regression
work already found: H4's VF2PostLayout no-op overhead only appears for **symmetric circuits on large maps
at opt-level 3** (≈1.9× at 16 q → >300× at 27 q), a corner the ≤8-qubit pilot never entered.

Fixing the selector cannot fix either problem. Fixing the corpus can.

## 2. Measured cost curve (sandbox, illustrative)

Qiskit 2.4.2, basis `cx/rz/sx/x`, seed 1234, transpile-only CPU seconds, using the repo's own
`circuits.py` / `backends.py`. Full data: `results/costcurve-sandbox/costcurve_sandbox_2026-08-04.json`.
**These are shared-CPU sandbox numbers — illustrative of shape only; final calibration is re-measured and
frozen on the parent machine (§6).**

| Regime | Example unit | CPU s |
|---|---|---|
| Cheap floor | ghz / qaoa_linear, n≤27, opt1 (any map) | 0.004–0.006 |
| qaoa stays cheap even wide | qaoa_linear n=65 heavy_hex opt3 | 0.057 |
| opt3 multiplier | qft n=27 line: opt1 → opt3 | 0.055 → 0.339 (6.2×) |
| Mid | qft n=12–27 opt3; random_clifford n=20–30 | 0.06–0.73 |
| Heavy | qft n=40 / 65 / 100 heavy_hex opt3 | 0.80 / 1.55 / **2.61** |

Transpile-only spread from cheapest to qft-100: **~685×**. Two design facts fall out:

- **Family and opt are the primary cost levers.** QFT and random_clifford (dense two-qubit structure) grow
  steeply with width; GHZ and QAOA-linear (sparse) stay cheap at any width. opt3 multiplies dense-family
  cost several-fold. So cost heterogeneity is obtained by *mixing families and opt levels across width*,
  not by width alone.
- **The oracle is a second, independent cost axis not yet exercised.** `expected_cost = baseline_cost_s +
  oracle_est`, and the exact-unitary oracle forms an operator of dimension 2ⁿ (cost ~O(4ⁿ)). At n ≤ 8 that
  is trivial; at n = 12 it is a 4096×4096 operator (hundreds of MB, ~seconds). The pilot's n ≤ 8 cap hid
  this. Allowing exact-unitary-oracle units up to n = 12 adds an expensive tail *on the oracle side*, which
  is exactly what the cost model reasons about.

## 3. The corpus that makes the budget bind

Three cost levers (family × width, opt level, oracle tier) are combined so per-unit cost spans **≥3 orders
of magnitude** and the full suite costs **≥10× the pr budget**, giving a real pr / nightly / release ladder.

**Axes (extend `static_manifest.py`; current `DEFAULT_WIDTHS = (5,8,12,18)`):**

- **Families:** `ghz`, `qaoa_linear` (cheap, sparse) + `qft`, `random_clifford` (expensive, dense). Keep
  all four — the cheap two provide the "many trivial tests" realism, the dense two provide the costly tail.
- **Widths (tiered):** small {5, 8, 12}, mid {18, 27}, large {40, 65}, xlarge {100} (dense families only).
- **Backends:** `line` (cheap routing), `heavy_hex` (realistic, heavier routing); `grid` optional.
- **Opt levels:** 1 and 3 (opt3 is the dense-family cost multiplier).
- **Oracle tiers by width (confirm thresholds in `static_manifest.py`):** exact `unitary` for n ≤ 12
  (now a genuine cost driver), `sampled_sv` for 13–27, `structural` above 27. Do **not** cap below 12, or
  the oracle cost axis stays hidden as it did in the pilot.

**Two things must hold for the budget to bind:** (i) per-unit cost must span orders of magnitude, and
(ii) the CI budgets must be sized to the suite. The pilot failed both — a homogeneous n≤8 corpus *and* a
placeholder 120 s budget against a 0.3 s suite. `configs/budgets.yaml` states its tier values are
placeholders ("calibrate against baseline costs"), so the clean fix is to **calibrate budgets as fractions
of the measured full-suite cost T_full** (standard practice for selection budgets), which guarantees binding
once the cost spread is present. Target invariants:

- per-unit cost `max/min ≥ 1000×` (transpile + oracle) — the corpus provides this.
- budgets set from the suite: **pr ≈ 5 % · T_full, nightly ≈ 40–70 % · T_full, release = 100 %** — a genuine
  tier ladder that binds by construction.
- binding sanity: under the pr budget, a cheapest-first order must **exclude the costly (fault-bearing) tail**.

### 3.1 Empirical verification (2026-08-04, sandbox — machinery + binding only, no held-out detection)

Generated with the new `--profile costhet` path (§6): **116 units**, all 29 family/width combos construct
(incl. qft-127, random_clifford-40); the pilot manifest is untouched (still 64 units). Measured transpile
cost over the 116 units (`results/costcurve-sandbox/costhet_unit_costs_2026-08-04.json`):

- per-unit cost **0.0041 s → 4.34 s = 1061× spread** — invariant (i) **met**;
- T_full = 34.8 s (sandbox, transpile-only). Under **calibrated** budgets: **pr = 5 % · T_full = 1.74 s fits
  88/116 units but excludes 28 of the 29 costliest** (nightly = 50 % fits 110/116, excludes 6/29). The budget
  now **binds and applies pressure exactly on the expensive units a naive selector drops** — invariant (ii) met.

So on this corpus the fix works with calibrated budgets. If a **fixed wall-clock** pr budget is preferred
instead, scale T_full ~35× (push qft widths past 127 and/or seed-replicate the heavy corner) so a fixed
120 s binds hard. Either way: keep the cheap tail broad and grow cost via the dense/high-width tail, not the
full cross-product (random_clifford stays capped — its transpile cost explodes with width).

## 4. De-saturating detection (the coupling that makes the study meaningful)

A binding budget is necessary but not sufficient — detection must also vary across units, or selectors
still tie. The design makes each fault **regime-specific**, so only a subset of units reveals it and
ordering matters:

- **Performance (H4, VF2PostLayout no-op #14120):** manifests only in the **expensive** corner (wide,
  symmetric, large map, opt3). A cost-aware selector that shuns expensive units will *miss* it → a real
  precision-vs-cost tradeoff. This is the paper's thesis in one example: the fault hides in the costly
  tests.
- **Contract/metadata (H1 #14603, H2 #14919):** manifest when routing actually permutes, i.e. width above
  the native connectivity on line/heavy_hex; detected by the property/contract oracle (Secondary track).
- **Global phase (#14956, #16201):** family-specific — phase-bearing circuits (QFT has `cp`/phase gates;
  GHZ does not).
- **Determinism (#14730, #16237):** target/seed-specific.

Apply the same principle to the **mutation cohort**: scope each mutation so it is *not* universally
detectable (e.g. mutate an optimization pass that only fires at opt3, or a routing pass that only engages
above a width threshold). The goal is a corpus where the detection matrix is sparse and structured, not
saturated.

The expected payoff, which links this study to the authors' companion paper: **cost-aware selection matters precisely
because the output-invisible and performance faults concentrate in the expensive, high-width tests** — so a
transparent, severity-and-cost-aware `risk_score` has room to beat cheapest-first and random, or, if it
does not, the powered negative result is itself informative.

## 5. Leakage-safety: freeze order (do not skip)

1. **Pre-declare** this corpus spec and the calibration procedure before observing any held-out detection
   outcome. (This document + `configs/corpus_costhet.yaml` are that pre-declaration.)
2. **Calibrate on the parent machine** (quiet, pinned process): baseline_cost_s = ≥5-run median CPU
   process-time per unit — **implemented** in `ground-truth` via `measure_cost` (clean/un-instrumented,
   1 warmup discarded, outside `tracemalloc`; min/median/max/IQR recorded per unit; run with
   `--cost-repeats 5`). The old single instrumented run was ~5.5× inflated on a cheap unit. Also refine
   `ORACLE_COST_EST` per width tier from *measured* oracle cost (the 0.05 constant is only valid at tiny n).
3. **Freeze**: write the calibrated costs + final counts into a versioned config; bump the manifest schema
   version; never tune on held-out detection.
4. Re-run the **leakage-absence gate** and confirm all six validity gates still pass.

## 6. How to run it on the parent setup

```
# 1. Extend the enumeration grid + oracle tiers in src/cart/manifest/static_manifest.py
#    (DEFAULT_WIDTHS, families, backends, opt levels, oracle-tier width thresholds).
python -m cart.cli manifest                         # regenerate data/manifest_static/manifest_static.json
# 2. Calibrate + label on the parent (quiet machine), larger unit budget:
python -m cart.cli ground-truth --unit-limit <N>    # per-unit baseline cost + oracle labels
# 3. Powered evaluation (feeds B3):
python -m cart.cli evaluate --split all --random-seeds 20
```

Then verify the corpus actually binds the budget **before** trusting any selection result:

- full-suite cost ≥ 10× pr budget; per-unit cost spread ≥ 1000×;
- pr/nightly selectable fractions ≈ 5–10% / 40–70% / 100%;
- detection matrix is sparse (no fault caught by all units; no unit catching all faults).

## 7. B1 acceptance criteria

A frozen, pre-declared corpus spec in which, on the parent calibration: (i) full-suite cost ≥ 10× the pr
budget, (ii) per-unit cost spans ≥3 orders of magnitude, (iii) pr/nightly/release form a real ladder, and
(iv) the detection matrix is de-saturated. Only then does B3 (the powered comparison) produce a
meaningful result.
