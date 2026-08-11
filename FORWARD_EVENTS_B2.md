# B2 — CLOSED (2026-08-05): forward cohort settled at 2 verified events

Ledger at **15 events**, `validate_ledger.py --expect 15` green. **Forward cohort = 2:**
`hist-vf2postlayout-noop` (#14120, `confirmed`) and `fwd-applylayout-registers-14904` (`verified`). Reported
**per event** under `FORWARD_COUNT_DECISION.md` (below the ≥3 threshold for a pooled temporal-generalization
claim). Paper 1's artifact stays frozen at 14 events — that divergence is deliberate; do **not** sync the
15-event ledger into `paper1-artifact`.

## Final candidate dispositions

| candidate | channel | outcome |
|---|---|---|
| `hist-vf2postlayout-noop` (H4 #14120) | performance | **verified** (Stage-2), Primary track |
| `fwd-applylayout-registers-14904` (#15024 fix) | contract/metadata | **verified** — register drop from `initial_layout`, Secondary track |
| `fwd-elide-14603` | contract/metadata | dropped — 1.3.0 era wall |
| `fwd-pr14919` | contract/metadata | dropped — 1.1.0 era wall |
| `fwd-pr16215` | global phase | dropped — introducing commit never located (bisection audit) |

## The #15024 retrace (how #14904 became the introducing commit)

The PR-referenced `ccc2c77b` (#14778) was **measured and rejected**: the forward pair `e364cd96`→`ccc2c77b`
gave identical `initial_layout.get_registers()` at all four opt levels — #14778 never introduced the fault.
A git pickaxe over the two files the fix patched, inside a measured good/buggy bracket, found the real
introducing commit **`dd8269969` — "Port `ApplyLayout` to Rust" (#14904)** (last-good parent `01610e98349e`).
`verify_15024_contract.py` fired **4/4** at every optimization level, output oracle blind on both sides,
`fault_detected=true`; promoted via `add_forward_event.py --verified-from`. Full detail in
`FWD_15024_RETRACE.md` and `data/events/PROVENANCE_BACKLOG.md`.

## Two findings for the manuscript (Discussion / B5)

1. **A recurring Rust-port defect pattern.** #14904 (`ApplyLayout`) is the **second** output-invisible
   regression introduced by a Rust port of a transpiler pass silently dropping Python-side layout metadata —
   the first being H1 (#14603), introduced by `cbb4d5d5` "Port `ElidePermutations` to Rust" (#13094). Two
   independent instances make this a named, recurring pattern, and both are invisible to output-equivalence
   oracles — stronger than either case alone.
2. **Targeted triggers must come from the fix's own regression test, not the PR title.** Three inert generic
   triggers now attest to it: #14939 (Paper 1), and the first pass at #15024; the #15024 detector only fired
   once mirrored exactly from `test_preset_passmanagers.py::test_layout_registers_preserved`. The detection
   mechanism and the trigger are a matched pair.

## Reusable verifiers left in `scripts/` (all `--baseline-python`/`--candidate-python`/`--out`)

- `verify_15024_contract.py` — register-preservation (`initial_layout.get_registers()`), opt-swept; **used**.
- `verify_16215_forward.py` — global-phase forward differential; kept for a properly traced global-phase pair.
- `bisect_regression.py` — now exits non-zero / inconclusive when no `bad` probe is ever seen (was silently
  echoing the input `--bad`); `classify_search` covered by `tests/test_bisect_regression.py`.
- `add_forward_event.py` (`--verified-from`, refuses to promote without `fault_detected=true`, mirrors to
  `events.csv`) and `validate_ledger.py` (`--expect N`) are the parent-synced patched versions.

## What now carries the paper

B2 is done; the **mutation cohort (n=9) is the headline**. Priority is the B1 **cost calibration** on the
parent, then freeze `configs/corpus_costhet.yaml` (`version: 1`, `frozen: true`) and B3 runs end-to-end.
`report_b3.py` renders the forward cohort **per event only** (n=2: no bootstrap CI, no Cliff's δ, no aggregate
win/tie/loss); the mutation cohort gets the full aggregate comparison.

## Paper 1 revision-list items (do NOT act — Paper 1 is frozen)

For when the supervisor's comments arrive: (1) #16215 is Level-2 (fix-code + regression-test inspection), not
bisection-traced — fix the wording; (2) relabel the backlog's old "bisection-traced" phrasing; (3) describe
Table 3's H1/H2 introducing commits as PR-read/pickaxe, not bisection. No measured result changes.
