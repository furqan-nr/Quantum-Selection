# Provenance backlog — forward-regression candidates (RESOLVED 2026-08-05)

The canonical event ledger (`events.csv` / `events.json`) is now **15 events** (6 historical-source + 9
mutation), validator green (`validate_ledger.py --expect 15`), with the **forward cohort = 2**:
`hist-vf2postlayout-noop` (#14120, `confirmed`) and `fwd-applylayout-registers-14904` (`verified`).
All four original forward-regression candidates have been dispositioned; this backlog is closed.

## Candidate dispositions (final)

| candidate_id | channel | introducing commit | last-good parent | fix PR | disposition |
|---|---|---|---|---|---|
| fwd-elide-14603 | contract/metadata | `cbb4d5d5` (#13094, Rust port) | `c34743a8` | #14603 | **dropped** — introducing commit builds at 1.3.0; the 2.x oracle harness cannot run it (era wall) |
| fwd-pr14919 | contract/metadata | `df59ab0c` (#11399) | `090b2b19` | #14919 | **dropped** — introducing commit builds at 1.1.0 (era wall) |
| fwd-pr16215 | global phase | `f2f85a94` (#16219, *mimalloc bump*) | `a241dd19` | #16215 | **dropped** — introducing commit never actually located; the bisection echoed the input SHA (see BISECTION_AUDIT.md). `f2f85a94` was measured `good` |
| fwd-tlayout-registers-15024 | contract/metadata | ~~`ccc2c77b` (#14778)~~ → **`dd8269969` (#14904)** | ~~`e364cd96`~~ → **`01610e98349e`** | #15024 | **PROMOTED** as `fwd-applylayout-registers-14904` (verified) — see retrace below |

## #15024 retrace (why the introducing commit changed)

The `ccc2c77b` (#14778) value came from a **PR reference, not a converged trace**, and it was **wrong**.
Building the forward pair `e364cd96` → `ccc2c77b` and running `verify_15024_contract.py` returned
**negative**: `initial_layout.get_registers()` was identical (`[a(2), b(1,Ancilla)]`) on both sides at all
four optimization levels — so #14778 never introduced the fault (`FWD_15024_RETRACE.md`). The detector was
sound (it had already fired 4/4 at the fix boundary with a clean `[a,b]` vs `[]` signal); the provenance was
not.

With a **measured bracket** (`ccc2c77b` proven good, `bb100f83^` proven buggy — 91 first-parent commits), a
git **pickaxe** over the two files the fix patched (`crates/transpiler/src/transpile_layout.rs`,
`crates/transpiler/src/passes/apply_layout.rs`) shortlisted two commits. The first was it:

- **introducing (candidate/buggy): `dd8269969763866dd828128369a500e624c49c83`** — "Port `ApplyLayout` to Rust
  (#14904)", first tag 2.2.0
- **last-good (baseline): `01610e98349e`**

`verify_15024_contract.py` fired **4/4** at all optimization levels, output oracle blind on both sides,
`fault_detected=true` — promoted as `fwd-applylayout-registers-14904` via
`add_forward_event.py --verified-from <verifier.json>` (which now refuses to write without a
`fault_detected=true` record) and confirmed by `validate_ledger.py --expect 15`.

## Finding worth stating in the paper (Discussion)

This is the **second** output-invisible regression introduced by a **Rust port of a transpiler pass** that
silently dropped Python-side layout metadata — the first being H1 (#14603), introduced by `cbb4d5d5`
"Port `ElidePermutations` transpiler pass to Rust" (#13094). Two independent instances make "Rust port drops
Python-visible layout/permutation metadata" a **named, recurring defect pattern** in Qiskit, both invisible
to output-equivalence oracles. It pairs with the trigger lesson: targeted triggers must be derived from the
fix's own regression test, not the PR title (#14939 inert in Paper 1; #15024-v1 inert; #15024-v2 positive
once mirrored from `test_layout_registers_preserved`).

## Procedure (retained for any future candidate)
1. `git blame` the fix PR's changed lines at the parent to find the prior logic.
2. Establish a **measured bracket** (a proven-good and a proven-buggy revision), then **pickaxe**
   (`git log -S` / `find_introducing_commit.py`) over the exact files the fix patched — this locates the
   commit that changed the specific lines and has none of the bisection script's failure modes.
3. Record `baseline = I^`, `candidate = I`, `pair_orientation = forward`,
   `evaluation_cohort = forward_regression`.
4. Build both revisions and run the matched oracle; promote **only** on `fault_detected=true`
   (`add_forward_event.py --verified-from`), then `validate_ledger.py --expect <N>`.
