# Bisection audit — no bisection run ever located an introducing commit

Found 2026-08-04 while era-checking the B2 candidates. This changes the `fwd-pr16215` plan and adds one
wording item to Paper 1's revision list. **No result in either paper is invalidated** — see "What is not
affected" at the end.

## The mechanism

`scripts/bisect_regression.py` (line ~272) initialises the answer to the *input* endpoint:

```python
first_bad = bad_sha              # <-- default
while lo <= hi:
    ...
    if v == "bad":
        first_bad = commits[m]   # <-- only ever overwritten here
```

So if **no probe returns `bad`**, the script still reports `introducing_commit = bad_sha`, the revision you
handed it, and prints it as `introducing commit (first BAD)`. It never signals that the search failed.

## Every trace in `results/` shows exactly that

| trace | probes | good | **bad** | skip | reported `introducing_commit` | = input `bad` endpoint? |
|---|---|---|---|---|---|---|
| `bisect-14603-*` | 6 | 0 | **0** | 6 | `7c3890da097c` | yes |
| `bisect-14730-*` | 6 | 6 | **0** | 0 | `056c6413b03a` | yes |
| `bisect-16215-*` | 9 | 9 | **0** | 0 | `f2f85a9476e3` | yes |
| `bisect-16237-*` | 8 | 8 | **0** | 0 | `34cb82b4524c` | yes |

**Not one `bad` probe across four runs.** For #14603 all six probes were `skip` (build failures), so that
run produced no information whatsoever. Every reported "introducing commit" is an echo of the input.

The #16215 case is the clearest tell: the reported introducing commit `f2f85a9476e3` is
**"Bump mimalloc from 0.1.50 to 0.1.51 (#16219)"** — an allocator dependency bump, implausible as the cause
of a global-phase regression — and the trace probed that very commit **`good`**.

## Consequence for Paper 2 (act on this)

**Drop `fwd-pr16215`.** It has no credible introducing commit, and the trace rates both sides of the
proposed forward pair `good` under the very oracle (`global_phase`) the verification would use. Running
`verify_16215_forward.py` on that pair would almost certainly show nothing, and a positive would not be
attributable. Keep the script — it is well built and reusable — but point it at a properly traced pair.

Revised candidate table:

| candidate | era (git tag, verified) | status |
|---|---|---|
| `hist-vf2postlayout-noop` (H4 #14120) | 2.x | **confirmed** — the only verified forward event |
| `fwd-elide-14603` | **1.3.0** | drop — era mismatch (harness is 2.x) |
| `fwd-pr14919` | **1.1.0** | drop — era mismatch |
| `fwd-pr16215` | 2.5.0 | **drop — introducing commit not established** |
| `fwd-tlayout-registers-15024` | **2.2.0** (`ccc2c77b` → first tag 2.2.0; parent `e364cd96` → 2.2.0) | only remaining viable candidate |

Era column is now settled from git metadata (`git tag --contains`), not inferred from PR numbers, and it
confirms the Paper 2 session's reasoning about #15024: it is genuinely 2.2.0, the same major as the oracle
harness, so it will not hit the API-drift wall.

**Realistic forward count is 2 (H4 + #15024 if it verifies), not 3.** Plan for that now: either trace a new
candidate properly with `scripts/find_introducing_commit.py` (git pickaxe, which locates the commit that
changed the specific lines and does not have this failure mode), or report per-event results under the
claim-scope rule instead of a pooled temporal-generalization claim.

**Fix the tool before relying on it again.** `bisect_regression.py` should exit non-zero with an explicit
"no bad probe found — search inconclusive" when `first_bad` is never reassigned, instead of silently
returning the endpoint. Also worth failing loudly when every probe is `skip`.

## Consequence for Paper 1 (revision-round wording, not a results change)

Paper 1 is frozen and with the supervisor, so **nothing was edited**. Add to the revision list:

1. The manuscript says, twice, that #16215 was *"traced to its introducing commit by automated bisection"*
   (§6.2 and the historical-events paragraph). The artifact does not support that phrase. Replace it with
   the provenance that is supported: #16215 is corroborated by **fix-code and regression-test inspection
   (Level 2)**, which §6.3 already states correctly and independently.
2. `data/events/PROVENANCE_BACKLOG.md` labels all four `fwd-*` candidates "bisection-traced". That wording
   should become "introducing commit read from the PR / pending trace", since none came from a converged
   bisection.
3. Table 3's introducing commits for H1 (`cbb4d5d5`, #13094 "Port ElidePermutations to Rust") and H2
   (`df59ab0c`, #11399) do **not** appear in any bisect trace, so they came from PR reading or pickaxe,
   not bisection. Those values look right, but the column's provenance should be described accurately.

## What is not affected

The mining headline (19/68 = 28%, Wilson CI 19–40%), the κ values, the cross-SDK replication, the six
source-evidenced faults, the held-out oracle evaluation, and the Level 1/2/3 evidence grading are all
independent of bisection. #16215 is graded **Level 2** in §6.3 on fix-code and regression-test inspection,
which stands on its own. This is a provenance-wording problem confined to how the introducing commits were
described, not a defect in any measured result.
