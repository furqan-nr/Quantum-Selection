# Phase A pre-registration record — EMSE scale-up (decomposed selector + expanded mutation cohort)

**Timestamp: 2026-08-13T03:36:26Z.** At this moment, no ground-truth label for any scale-up mutation
event (the 10 new operators or the 19-event cohort they form with the original 9) and no detection
outcome for the `decomposed` selector had been read, computed, or observed. Phase B (the fresh Kaggle
cost calibration and labeling run) has not started. This file, and the SHA-256 hashes below, are the
pre-registration evidence for Items #1 and #2 of `PAPER2_EMSE_SCALEUP_PLAN.md` — the design
commitments below are fixed *before* any label exists to tune them against.

**Why a hash manifest instead of a git commit hash.** `PAPER2_EMSE_SCALEUP_PLAN.md`'s Phase A5
called for "one commit... this commit hash is what §11/Methods cites as the pre-registration
evidence." This sandbox has no `.git` directory in its view of the project (the real repository lives
in the user's own environment, outside this sandbox's reach). A SHA-256 hash of each file serves the
identical evidentiary purpose — content-addressed, tamper-evident, checkable — and is the same
mechanism this project already uses for write-once raw artifacts (`raw_sha256` in every
`data/raw/.../result.json`) and the environment lock (`requirements.lock.sha256`). **Action needed
from the user:** run `git add` + `git commit` on exactly these files in the real repository; the
commit's own hash then becomes the citable pre-registration reference, and the SHA-256 values below
let you (or a reviewer) confirm the committed content is byte-identical to what was fixed here, before
Phase B ever touched Kaggle.

## Files this record covers (all new except the last three, which are modified)

```
9a2b90d75795c2ed764e6ec3f576f72068083b6d5f75c422033878185b4edd32  src/cart/events/mutations_scaleup.py
3a2ff2dbd7558a49296ebc4074175b5207db2570b70d3bcb48ef5f151eaac3d8  src/cart/selectors/decomposed.py
3e93962c5265a428d41058d7cc80aeebeb665db2684348a28656f11eb167592f  src/cart/selectors/registry_scaleup.py
d55285dcdee26c76140c190b4487a6077f4a223a6e5a47f6db631501b2c61bef  tests/test_decomposed_selector.py
99e345e6842a87c2281fba1466179233ab46b72d4e10033b0a471bdd27b1bfb1  tests/test_scaleup_operators.py
ba04b68cb209e13bb888860a4440fa0bc2be3c26e442a5947ada2573f3bc6cf8  src/cart/metrics/evaluate.py
49d526826afde4e52b6d02556d41af6811542522d8a287640abf53c7a0f04cc1  src/cart/gates/validity.py
1a3dc1ac6fd71c38d53cd27908484922f49102310a6fdf85f7380942b1dab0e7  src/cart/cli.py
```

Regenerate and compare with: `sha256sum <paths above>` from the repo root.

## What is being pre-registered

**The decomposed selector's design** (`src/cart/selectors/decomposed.py`): diversity first
(greedy coverage of `(circuit_family, backend_id)`), cost second, severity — `CIRCUIT_CRITICALITY`
weighted by connectivity pressure, reusing `proposed.py`'s own severity proxy — only as a final
tie-break. This is exactly the mechanism the manuscript's §6.4/§7 diagnosis and §9 future-work
sentence already commit to on paper; nothing here was chosen by looking at a scale-up result, because
no scale-up result exists yet.

**The 19-event mutation cohort** (`src/cart/events/mutations_scaleup.py`): the original 9 operators
(imported from `mutations.py`, not modified) plus 10 new ones — `remove_consolidate_blocks`,
`remove_elide_permutations`, `remove_basis_translator`, `downgrade_layout_dense`,
`downgrade_translation_synthesis`, `seed_drift`, `insert_redundant_sx_quad`,
`combo_no_elide_synthesis_translate`, `combo_no_consolidate_dense_layout`,
`combo_dense_layout_basic_routing`. Each was checked (structurally live, non-hanging,
semantics-preserving) against this corpus's actual circuit families *before* being locked in here —
that is a structural check, not a label read (see `mutations_scaleup.py`'s own docstring for exactly
what was checked and what was dropped as dead weight or unsafe). The plan's original target was 18
new operators (27 total); rigorous verification supported 10 (19 total), and that is what is
pre-registered — not padded to the aspirational number.

## What happens after this point is committed

Phase B (fresh Kaggle cost calibration into a parallel `data_scaleup/` root, never touching `data/`)
reads the first label. Any change to `decomposed.py`'s ranking logic or to which operators are in
`MUTATION_OPERATORS_SCALEUP` after that point would not be leakage-safe against this cohort and would
need its own fresh freeze, exactly as the primary result's own re-tuning rule already states.

## Supporting verification (not part of the pre-registration commitment itself, informational)

- Test suite: 80 passed, 1 pre-existing unrelated failure (`test_targeted`), before and after this
  work — confirmed via `pytest -q`.
- Primary frozen result unaffected: re-ran `cart.cli evaluate` with default arguments (no `--data-dir`,
  no `--selectors`) and diffed against the committed `results/evaluation_costhet_frozen.json` — every
  detection metric (recall@20%, normalized TTFR, AUC) is byte-identical; only `mean_selection_overhead_s`
  (a wall-clock timing diagnostic, not a frozen headline number) differs, as expected from measuring on
  a different machine at a different time.
- CLI wiring smoke-tested end-to-end (`--selectors scaleup` against the primary data, read-only,
  written only to a scratch path outside the repo) to confirm `decomposed` is scored correctly
  alongside the five baselines and `proposed` before Phase B depends on this path.
