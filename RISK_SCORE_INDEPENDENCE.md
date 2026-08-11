# risk_score weight independence from the mutation operator set (2026-08-10)

## The concern

From the minor-concerns review: whether the 9 mutation operators were fixed before `risk_score`'s
weights were chosen — no visibility into that timeline.

## Why timeline evidence isn't available

The repository history is too coarse to answer this by date. `git log --follow` on both
`src/cart/events/mutations.py` and `src/cart/selectors/proposed.py` shows both files landing
together in the same two commits:

```
551be03 2026-07-23 divided the paper in 2
cb55a86 2026-07-04 Initial commit
```

Sixteen commits total, whole-repo squashes with generic messages — not a per-feature history that
could establish which was authored first. Claiming an ordering from this history would not be
defensible to a referee.

## Why the ordering question turns out not to matter

The stronger and checkable claim is structural: **`risk_score`'s weight tables have no parameter
that mutation-operator identity could feed into**, regardless of which was written first.

`src/cart/selectors/proposed.py:33-34`:

```python
CIRCUIT_CRITICALITY = {"ghz": 1.0, "qft": 1.5, "qaoa_linear": 1.3, "random_clifford": 1.2}
ORACLE_CONFIDENCE = {"unitary": 1.0, "sampled_sv": 0.8, "property": 0.5, "structural": 0.3}
```

Both lookup tables are keyed on properties of the **test corpus and oracle design** — circuit
family and oracle type. These are manifest-level attributes, fixed by what tests exist, not by
what faults are injected into them.

The 9 mutation operators (`src/cart/events/mutations.py`, METHODOLOGY §1.5) sit on a different
axis entirely: each is a deterministic transform of the preset pass manager, identified by
operator name / `fault_type` (disable-optimization-loop, downgrade-routing,
drop-vf2postlayout, etc.), acting on transpiler pass stages. Nothing in `mutations.py` references
circuit family or oracle type, and nothing in the weight tables references operator identity or
`fault_type`. There is no shared key, so there is no code path by which knowing the mutation set
could have informed the weight values, or vice versa.

## This is a stated design rule, not an incidental fact

METHODOLOGY.md §4.1, "No label leakage":

> None of these components uses the candidate's `fault_type`, runtime, quality metrics, or
> outcome (§4.3)... The true `fault_type` and observed severity are used only post-hoc to weight
> reporting (e.g. severity-weighted recall), never to rank.

METHODOLOGY.md §4.3, "Data Leakage Prevention" — the selector may use only candidate change
metadata, test manifest metadata, baseline-version costs, and pre-`event_date` history. Candidate
runtime, quality metrics, and output labels are explicitly forbidden. Mutation-operator identity
isn't on the permitted list at all.

The code comment at `proposed.py:32` ("Pre-declared component weights") matches this: the weight
values are fixed constants declared in the module, not fit or tuned against any observed mutation
outcome.

Traceability table entry (METHODOLOGY.md, row 3): "`expected_impact` de-leaked. Replaced
`fault_type`-severity weighting (unknown pre-execution) with oracle strength × circuit criticality
× backend/topology stress × historical stage-conditioned impact. `fault_type` used post-hoc only."
— i.e. an earlier design that *did* key on fault type was deliberately replaced for exactly this
reason.

## What to write in the paper

Not "the mutations were fixed first" (unverifiable from the history). Instead: `risk_score`'s
weight tables are indexed on circuit family and oracle type, properties of the test corpus
independent of the injected-fault set; the mutation operators are indexed on pass stage and
operator identity; the two never share a key. Combined with the pre-declared, `fault_type`-blind
design mandated in METHODOLOGY §4.1/§4.3, there is no mechanism by which the specific mutation
operators chosen could have shaped the weight values. This closes the leakage concern without
resting on commit-timeline evidence the repository cannot actually provide.
