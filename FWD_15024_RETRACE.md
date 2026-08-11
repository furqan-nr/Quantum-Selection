# #15024 forward run — negative at #14778, and the real introducing commit re-traced

## What happened (2026-08-05)

Forward run on `e364cd96` (parent of #14778) vs `ccc2c77b` (#14778), `results/fwd-tlayout-15024/`:

| level | baseline `get_registers()` | candidate `get_registers()` | output oracle |
|---|---|---|---|
| opt0–opt3 | `[a(2), b(1,Ancilla)]` | `[a(2), b(1,Ancilla)]` — **identical** | blind on both |

`fault_detected=False`. **#14778 ("Add TranspileLayout struct to rust") did NOT introduce the fault.**

**This is a tracing failure, not a detector failure.** The same detector fired 4/4 at the fix boundary with
a clean `[a,b]` vs `[]` signal. It works. The `PROVENANCE_BACKLOG.md` row naming `ccc2c77b` as the
introducing commit is simply wrong — it came from PR reference, not from a converged trace.

## Ledger incident — reverted

`add_forward_event.py` spliced `fwd-tlayout-registers-15024` into `events.json` **despite the negative
verification**, because the script has no gate: it never checks for a verification record. `validate_ledger.py`
caught it immediately (`JSON has 15 events, expected 14 ... belongs in PROVENANCE_BACKLOG.md`). The event was
removed; all three ledger copies are byte-identical and the validator passes at 14 events.

**Process fix worth making:** `add_forward_event.py` should refuse to write unless passed a path to a
verification JSON showing `fault_detected=true` for that event, or at minimum require an explicit
`--i-verified-this` flag. Right now a negative run followed by a copy-pasted promotion command silently
corrupts the ledger.

## The real introducing commit — narrowed to 2 candidates, zero builds

We now have a **proven bracket**: `ccc2c77b` is GOOD (registers preserved, measured) and `bb100f83^` is
BUGGY (registers dropped, measured). That is 91 first-parent commits.

Only **two** commits in that bracket touch either file the fix patched
(`crates/transpiler/src/transpile_layout.rs`, `crates/transpiler/src/passes/apply_layout.rs`):

| commit | date | subject |
|---|---|---|
| **`dd8269969`** | 2025-08-26 | **Port `ApplyLayout` to Rust (#14904)** ← prime suspect |
| `b712f98b6` | 2025-08-28 | Transpile C API (#14760) ← fallback |

`dd8269969` is chronologically first, and the precedent is exact: **H1's fault (#14603) was introduced by
`cbb4d5d5` "Port `ElidePermutations` transpiler pass to Rust (#13094)"**. A Rust port of a transpiler pass
dropping Python-side layout metadata is now a recurring, nameable failure mode in this codebase — which is
itself a finding worth a sentence in the paper.

Corroboration: the #15024 fix patches `crates/transpiler/src/passes/apply_layout.rs` (+2), i.e. it repairs
exactly the code `dd8269969` ported.

- prime suspect (candidate/buggy): `dd8269969763866dd828128369a500e624c49c83`, first tag 2.2.0
- its parent (baseline/good): `01610e98349e`
- fallback candidate: `b712f98b6`, parent `1064921158bb`

## Next: two builds, then the proven detector

```powershell
cd path\to\quantum-selection      # repo root
.\environment\setup\build_qiskit_event.ps1 -Sha 01610e98349e -EventEnvId fwd-tlayout-14904-base
.\environment\setup\build_qiskit_event.ps1 -Sha dd8269969763866dd828128369a500e624c49c83 -EventEnvId fwd-tlayout-14904-cand

python scripts\verify_15024_contract.py `
  --baseline-python environment\_builds\fwd-tlayout-14904-base\venv\Scripts\python.exe `
  --candidate-python environment\_builds\fwd-tlayout-14904-cand\venv\Scripts\python.exe `
  --out results\fwd-tlayout-14904
```

Promote **only** on `fault_detected=True`, and use the corrected SHAs:

```powershell
python scripts\add_forward_event.py `
  --event-id fwd-applylayout-registers-14904 --env-id fwd-tlayout-14904 `
  --fault-type contract_metadata --pr 15024 `
  --reference "ApplyLayout Rust port drops registers from initial_layout (introduced by #14904, fixed by #15024)" `
  --introducing-sha dd8269969763866dd828128369a500e624c49c83 --baseline-sha 01610e98349e

python scripts\validate_ledger.py
```

If `dd8269969` is negative, try `b712f98b6` / `1064921158bb` before giving up. If both are negative the fault
entered through a commit that does not touch those two files, and at that point stop: 91 commits is a
9-build bisection, which is not worth it under `FORWARD_COUNT_DECISION.md`.

## Standing status

Verified forward events: **1** (H4 #14120). All four original candidates have now failed, each for an
independent structural reason — two era walls, one never-located introducing commit, one wrong
PR-referenced commit. Under the locked decision that is fine: report per-event, pilot evidence, and treat
this re-trace as the opportunistic bonus it is. **The cost calibration remains the higher-priority task,
because the mutation cohort now carries the headline.**
