# Decision — plan for 2 forward events, report per-event (locked 2026-08-04)

**Decision.** Target **2** verified `forward_regression` events (H4 #14120 + `fwd-tlayout-registers-15024`)
and report the forward cohort **per-event** under the claim-scope rule. Do **not** gate the paper on a third
verified forward event. A pickaxe-traced third via `scripts/find_introducing_commit.py` is worth attempting
opportunistically, as a bonus, never as a blocker.

**Rationale.** Three separate attempts at a third event failed for independent structural reasons:
`fwd-elide-14603` (Qiskit 1.3.0) and `fwd-pr14919` (1.1.0) hit an era wall against a 2.x oracle harness, and
`fwd-pr16215` turned out to have no located introducing commit at all (see `BISECTION_AUDIT.md`). Gating the
write-up on a fourth attempt succeeding is the fragile path.

## This invokes a pre-declared rule — say so explicitly in the paper

`METHODOLOGY.md` §5.4 / risk register **R4** already states:

> *< 3 verified historical `forward_regression` events in the held-out cohort ⇒ no headline
> comparative-effectiveness claim; report per-event, classify as pilot evidence.*

This matters for how it reads to a referee. The rule was **pre-declared, not chosen after seeing the
outcome**, so invoking it is the leakage-safe posture the design promised rather than a retreat. Write it
that way: the threshold was set in advance, the evidence did not reach it, and the reporting scope follows
the rule automatically.

## The consequence to confront: where the headline claim now lives

If the forward cohort is per-event pilot evidence, then the **forward cohort cannot carry a headline
comparative-effectiveness claim**. That was previously the thing intended to lift Paper 2 above the "honest
null / feasibility section" status. So the headline has to come from somewhere else, and the coherent
answer is the **mutation cohort**:

- The original null was on nine synthetic mutations where detection **saturated** — every selector found
  everything, so nothing discriminated. That is a corpus-design problem, not a selector result.
- B1's cost-heterogeneous corpus exists precisely to make the budget bind. A powered comparison there is
  meaningful and **does not depend on the forward count at all**.
- The forward cohort then does what it is actually good for: per-event evidence of realism on real CI
  regressions, reported alongside and never pooled with the mutation cohort.

So the framing becomes: *powered comparison on the mutation cohort under a binding budget; forward cohort
reported per-event as corroborating realism evidence, under the pre-declared claim-scope rule.* That is
publishable and honest. What it is **not** is a pooled temporal-generalization claim, and the paper should
not imply otherwise anywhere.

## Concrete instructions for the B3 analysis (`report_b3.py`)

1. **Never pool the two forward events.** With n = 2 there is no bootstrap CI, no Cliff's δ, and no
   win/tie/loss aggregate for the forward cohort. Report **per event**: detection-at-budget at each budget
   level, and the selector ordering for that event.
2. Keep cohorts separate in every table (forward / fix_boundary / mutation), as already implemented.
3. Effect sizes and bootstrap CIs belong to the **mutation** cohort only, where n supports them.
4. Label the forward-cohort tables "pilot evidence, per-event (claim-scope rule §5.4)" in the caption, so
   the constraint travels with the table rather than living only in the text.

## Still gating everything

The `sv-15024` **fix-boundary** run is the next parent move. `verify_15024_contract.py` must fire where the
fault is known to exist before any forward build is justified. If it does not fire there, the forward count
stays at **1** (H4 alone) and the same per-event reporting applies with a single event — which is still
consistent with this decision, just thinner.

## Open to revision if

A pickaxe trace cheaply yields a genuine third event in the 2.x line, in which case the pooled claim becomes
available again and the framing can be revisited before write-up. Do not spend more than a bounded effort
on this.
