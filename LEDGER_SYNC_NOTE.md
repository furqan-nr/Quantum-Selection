# Ledger synced from canonical — read before continuing B2/B3

**Done 2026-08-04 from the Paper 1 session** (the only one that can reach the artifact repo).
Your `data/events/` was the **pre-correction** copy. It has been replaced with the canonical,
reproduction-verified ledger from `paper1-artifact/`. Your previous files are in
`data/events/_pre_sync_backup/` if you need to diff.

Synced: `events.csv`, `events.json`, `EVENTS_AUDIT.md`, `PROVENANCE_BACKLOG.md`,
`HISTORICAL_CANDIDATES.md`, and `scripts/validate_ledger.py`.
Verified: `Ledger OK: 14 events, CSV == JSON on 8 key fields, no forward leakage.`

## What changed — this invalidates part of the B2 conclusion

`reproducibility_status` was stale on four of five historical events:

| Event | was (your copy) | now (canonical) |
|---|---|---|
| H1 `hist-elide-permutations-mapping` | `rejected` | **`reproduced`** |
| H2 `hist-final-layout-composition` | `blocked` | **`reproduced`** |
| H3 `hist-vf2layout-determinism-1q` | `blocked` | **`reproduced`** |
| H4 `hist-vf2postlayout-noop` | `blocked` | **`confirmed`** |
| H5 `hist-vf2layout-panic-1p0` | `blocked` | `blocked` (unchanged) |

The `expected_observable_signal` fields for H1/H2 were also rewritten (H1 = full-pipeline passes,
isolated-pass raises; H2 = MR-1, not an output comparison).

**Three corrections to the B2 write-up:**

1. **The forward cohort is 1 event, not 5.** `events.csv` contains exactly one
   `evaluation_cohort = forward_regression` row: `hist-vf2postlayout-noop` (H4 #14120), now `confirmed`.
   The four `fwd-*` IDs are **not in the ledger** — they were deliberately removed during the Paper 1
   integrity cleanup so the study does not overstate its verified forward count.
2. **They live in `data/events/PROVENANCE_BACKLOG.md`**, which is now the authoritative source and is
   richer than `FORWARD_EVENTS_B2.md`: it gives, per candidate, the introducing commit **and the
   last-good parent SHA**, the fix PR, and a 4-step promotion procedure. Reconcile
   `FORWARD_EVENTS_B2.md` against it (note the ID is `fwd-tlayout-registers-15024`, not
   `fwd-tlayout-15024`).

   | candidate | channel | introducing (candidate) | last-good (baseline) | fix PR |
   |---|---|---|---|---|
   | `fwd-elide-14603` | contract/metadata | `cbb4d5d5` (#13094) | `c34743a8` | #14603 |
   | `fwd-tlayout-registers-15024` | contract/metadata | `ccc2c77b` (#14778) | `e364cd96` | #15024 |
   | `fwd-pr14919` | contract/metadata | `df59ab0c` (#11399) | `090b2b19` | #14919 |
   | `fwd-pr16215` | global phase | `f2f85a94` | `a241dd19` | #16215 |

3. **Do not count `fwd-elide-14603` as verified.** The backlog records that it was previously marked
   "reproduced" on the strength of bisection alone and was **deliberately demoted to pending** until a
   forward-pair oracle run exists. Bisection traces the origin; it does not verify the forward orientation.

**Promotion rule (from the backlog, step 4):** build both revisions from source and re-run the matched
oracle to confirm the fault reproduces in the **forward** orientation (output oracle blind, matched oracle
fires). Only then add the row to `events.csv`/`events.json`, update `n_events`, and re-run
`scripts/validate_ledger.py`. Never hand-edit a `reproducibility_status`.

## Build cache — the critical path is smaller than it looks, but not zero

*(Historical note: this describes the build cache as it existed on the original author's machine before
this package was extracted into its own repo. `environment/_builds/` is not part of this package — it is
large, machine-specific, and reproducible from the lockfiles in `environment/events/*.lock` — so a fresh
checkout of this repo starts with none of the builds below cached; rebuild whichever revisions you need via
`environment/setup/build_qiskit_event.ps1`/`.sh`.)*

At the time of writing there were **36 named from-source builds** cached locally, including
`sv-14603-{bug,fix}`, `sv-14919-{bug,fix}`, `sv-16215-{bug,fix}`, `sv-15024-{bug,fix}` and the `hist-*`
pairs for 14603 / 14919 / 14120. Those are **fix-boundary** builds.

Forward events need the **introducing-commit** side, and `cbb4d5d5` / `df59ab0c` are **not** cached under
those names. 33 `_bisect-*` trees exist and may cover some revisions, worth checking before rebuilding.
So the forward builds are real work, just less than starting from scratch.

## Where this leaves the gate

Claim-scope needs **≥ 3 verified forward regressions**; you have **1** (H4). Two more forward-pair
verifications are the genuine critical path for B3. `fwd-elide-14603` and `fwd-pr14919` remain the
fastest two, because their fix-boundary sides are already built and characterised.

## Green light on the B3 scaffolding

Building the analysis/reporting scaffolding now is correct and leakage-safe, with two constraints:

- Write it against the existing `evaluate.json` schema and test it on **mock/synthetic** data only.
- Do not compute or print any selection comparison numbers until the design is frozen on the parent —
  `configs/corpus_costhet.yaml` stays `frozen: false` until then.

## Isolation (unchanged)

Paper 1 is frozen and with the supervisor. Nothing in Paper 2 may write to
`Paper 1 - Observability/` or `Qautum Transpiler Observability/`. This sync was one-way **into** Paper 2;
Paper 1's files were verified unchanged afterwards (`PAPER.pdf` md5 `d4fc2e8f`, `build_paper.js` `aa75972f`,
artifact `events.csv` `89d54786`).
