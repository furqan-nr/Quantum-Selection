# Phase D: real Qiskit transpiler regressions detectable by Qiskit's own unit tests

Compiled 2026-10-18 (sandbox research + wheel-pair pilots). Nothing else in the repo was modified.

## 1. Key findings first

1. **Wheel pairs replace most Rust builds.** Many regressions start or end at a *released* version, so the
   buggy and good states are both on PyPI as wheels (pre-releases too: `qiskit==2.2.0rc1` installs). Test
   files come from the matching **sdist** (`pip download --no-binary :all: qiskit==X`; the sdist ships
   `test/`, but not `releasenotes/`). Diffing sdists of consecutive patch releases gives the fix's code and
   test diff without git.
2. **Pre-existing tests do not detect these regressions, by construction.** Every introducing PR passed CI.
   Measured once: the full 2.2.2 transpiler+compiler slice, run against the buggy 2.2.2 wheel, gave 0
   regression-related failures for the ConsolidateBlocks fault (C1). The only failures were 7 environmental
   ones (see section 4). So "detection" means **the fix's regression test, backported onto both sides**. For
   C2 no such test exists and one has to be added.
3. **Fix-boundary pairs and introduction-boundary pairs behave differently.** Fix tests sometimes encode
   behaviour or API that came after the feature, so they fail on the last-good version too:
   - C4: the exact-circuit assertion also fails on 2.4.2.
   - C5: the 2.5.2 test module cannot be imported on 2.4.2.

   Introduction-boundary detection therefore needs a transplanted or semantic (Operator-equivalence) variant
   of the test. Fix-boundary detection works as-is.

## 2. Ranked candidates (pilot = measured in this sandbox with pip wheels, 2026-10-18)

Columns: **Py/Rs** = where the fault lives (Py = Python-only, so it can be emulated by patching a wheel's
`.py`). **Fix-test only-after-fix?** = the test exists only after the fix, so backport it to both builds.

| # | Fault (issue / fix PR) | Type | Introducing → fixing | Affected releases | Py/Rs | Detecting test | Pilot result | Repro |
|---|---|---|---|---|---|---|---|---|
| C1 | `ConsolidateBlocks` instance reuse gives invalid output or panics. Issue [#15255](https://github.com/Qiskit/qiskit/issues/15255), fix [#15258](https://github.com/Qiskit/qiskit/pull/15258) (backport #15266) | functional (wrong output / crash) | `cb103d95` (#15083) → #15258 | 2.2.2 only | **Py** (`consolidate_blocks.py`) | `test/python/compiler/test_transpiler.py::TestTranspile::test_reuse_on_differing_circuits` (ddt 0–3). Yes, only after fix | 2.2.1 **4/4 pass**, 2.2.2 **2/4 FAIL** (opt 2,3), 2.2.3 4/4 pass. 2.2.2's own slice: 0 detection | **high** |
| C2 | H4: `VF2PostLayout` added at O3, output never applied (also runs with `initial_layout`). [#14120](https://github.com/Qiskit/qiskit/pull/14120), issue [#14867](https://github.com/Qiskit/qiskit/issues/14867), removed by #14905 (2.1.2), reworked by [#14869](https://github.com/Qiskit/qiskit/pull/14869) | performance / contract | `a8d23667` (parent `a18e1516`) → #14905 | 2.1.0, 2.1.1 | **Py** (`builtin_plugins.py`) | **None upstream**: #14905 added no test, and #14869's `test_level3_does_not_run_vf2post_layout_when_initial_layout_set` actually calls `optimization_level=1`, so it cannot catch this. Added test = #14867 reproducer, kept at `/tmp/run212/test_added_14120.py` (sandbox only; copy into the study before use) | 2.0.3 4/4 pass, 2.1.0 **1/4 FAIL** (opt 3), 2.1.1 **1/4 FAIL**, 2.1.2 4/4 pass | **high** (added test, must be pre-registered) |
| C3 | `ApplyLayout` Rust port drops registers from `initial_layout`. Issue [#15014](https://github.com/Qiskit/qiskit/issues/15014), fix [#15024](https://github.com/Qiskit/qiskit/pull/15024) | metadata / contract | `dd8269969` (#14904, parent `01610e98349e`) → #15024 | **2.2.0rc1 only** (pre-release) | Rs | `test_preset_passmanagers.py::TestPresetPassManager::test_layout_registers_preserved` and `..._with_allocated_ancilla` (ddt 0–3). Yes, only after fix | 2.2.0rc1 **8/8 FAIL**, 2.2.3 8/8 pass; 2.1.2 registers preserved (snippet, 4/4) | **high** |
| C4 | `CommutativeCancellation` miscompiles negative X-rotation runs (`%` sign). Issue [#16594](https://github.com/Qiskit/qiskit/issues/16594), fix [#16599](https://github.com/Qiskit/qiskit/pull/16599) (backport #16615) | semantic (wrong unitary) | `91081cc6d3` (#16191) → #16599 | 2.5.0 | Rs | `test_commutative_cancellation.py::TestCommutativeCancellation::test_negative_x_rotations` (ddt 2,3,4). Yes, only after fix | 2.5.0 **2/3 FAIL**, 2.5.1 and 2.5.2 3/3 pass. 2.4.2 3/3 fail (exact-circuit assertion needs the new feature) | **high** at fix boundary, **medium** at introduction boundary |
| C5 | `OptimizeCliffordT` S/Sdg swap gives non-equivalent output when the basis lacks sx/sxdg. Fix [#16729](https://github.com/Qiskit/qiskit/pull/16729) (backport #16735) | semantic | #15625 (SHA TBD) → #16729 | 2.4.0 to 2.5.1 | Rs | `test_clifford_t_passmanager.py::...::test_clifford_t_transpile_is_unitarily_equivalent` (ddt 0–3). Yes, only after fix | 2.5.1 **3/4 FAIL**, 2.5.2 4/4 pass. On 2.4.2 the 2.5.2 module fails to import (`generate_preset_clifford_t_pass_manager`), so the method has to be transplanted | **high** (fix boundary) |
| C6 | `VF2Layout` `max_trials=None/negative` broken by the Rust port (`OverflowError`). Fix [#14667](https://github.com/Qiskit/qiskit/pull/14667) (backport #14692) | crash / API contract | #14056 (VF2Layout to Rust, SHA TBD) → #14667 | 2.1.0 | Rs (Python wrapper identical in 2.1.0 and 2.1.1) | `test_vf2_layout.py::TestVF2LayoutLattice::test_hexagonal_lattice_graph_9_in_25_no_trial_limit` (ddt). Yes, only after fix | 2.0.3 pass, 2.1.0 **2/2 FAIL**, 2.1.1 and 2.1.2 pass | **high** |
| C7 | `Optimize1qGatesDecomposition` GIL deadlock with custom 1q gates. Issue [#16591](https://github.com/Qiskit/qiskit/issues/16591), fix [#16592](https://github.com/Qiskit/qiskit/pull/16592) (backport #16645) | crash (hang) | #15667 (multithreaded pass, SHA and first release TBD, likely 2.4.0) → #16592 | ≤2.5.0 | Rs | `test_optimize_1q_decomposition.py::...::test_custom_gate_in_target`. Yes, only after fix | 2.5.0 **hangs** (killed at 60 s), 2.5.1 pass in 0.4 s | **medium-high** (needs per-test timeout; multithreading depends on CPU count) |
| C8 | `ElidePermutations` mapping wrong with `PermutationGate`s. Issue #14602, fix [#14603](https://github.com/Qiskit/qiskit/pull/14603) | semantic + property-set contract | `cbb4d5d5` (#13094, Rust port, 1.3.0) → #14603 | 1.3.0 to 2.0.2 (fixed 2.0.3 / 1.4.x / 2.1+) | Rs | `test_elide_permutations.py::...::test_unitary_equivalence_permutation_gates`. Yes, only after fix | 2.0.2 **FAIL**, 2.0.3 pass | **high** (fix boundary), **medium** (1.2.4 vs 1.3.0: API drift) |
| C9 | `generate_preset_pass_manager` ignores `Target` timing constraints when there is no backend. Issue [#14329](https://github.com/Qiskit/qiskit/issues/14329) | contract | introducing unknown (≤2.0.0, may be long-standing) → fix in 2.1.2 | ≤2.1.1 | **Py** (`generate_preset_pass_manager.py`) | `test_preset_passmanagers.py::...::test_timing_constraints_from_target_no_backend`. Yes, only after fix | 2.0.3 FAIL, 2.1.0 FAIL, 2.1.2 pass | **medium** (fix boundary only; regression status unproven) |
| C10 | `VF2Layout`/`VF2PostLayout` panic "float scores must not return nan" (0·inf). Issue [#16267](https://github.com/Qiskit/qiskit/issues/16267), fix [#16285](https://github.com/Qiskit/qiskit/pull/16285) | crash | introduced during the 2.5 dev cycle (pickaxe `vf2.rs`, TBD) → #16285 | **no release** (issue reproducer passes on 2.4.2 and 2.5.0) | Rs | `test_vf2_layout.py::test_error_clipping`, `test_vf2_post_layout.py::test_error_clipping` | error_clipping tests pass on 2.4.2/2.5.0/2.5.2, so no wheel pair exists | **medium** (commit builds only) |

Backups, not recommended:
- **#14730** VF2Layout determinism (`test_determinism_all_1q`). Passes on the buggy 2.1.1 under 5 PYTHONHASHSEEDs, so the test does not detect it. Low.
- **#14919** `final_layout` composition. A latent bug with no introducing commit. Low.
- **#15068** VF2PostLayout limits. Python, performance, introduced by #14869 in 2.2.0, fixed 2.2.1. No unit test. Low.
- **#14969 / #15111** HoareOptimizer crash. Python, but not shown to be a regression. Low.

**Recommended set (8):** C1, C2, C3, C4, C5, C6, C7, C8. Add C9 and C10 if 10 are wanted.
- Python-only: **2 of 8** (C1, C2). **3 of 10** if C9 is counted.
- Rust: 6 of 8 (7 of 10). Only C3 and C10 strictly need source builds: C3 has the rc1 wheel, C10 has none.
- Type spread: functional/crash (C1, C6, C7, C10), semantic (C4, C5, C8), metadata/contract (C3, C9), performance (C2).

## 3. Including the two already-verified events

- **#14904/#15024 (C3)**: Qiskit's own fix test `test_layout_registers_preserved` detects it.
  - Fails 8/8 on 2.2.0rc1 and passes on 2.2.3.
  - Commit level (`01610e98349e` vs `dd8269969`) is not run here because the sandbox cannot build. It is
    expected to match, since the same assertion drove `verify_15024_contract.py` 4/4.
- **#14120 (C2)**: **no upstream test detects it.**
  - The nearest one (#14869) uses the wrong optimization level.
  - Detection needs the added #14867-reproducer test, which fails at O3 on 2.1.0 and 2.1.1 and passes on
    2.0.3 and 2.1.2.
  - Report it as "added test", not "Qiskit test".

## 4. Feasibility in the sandbox (measured)

- **git clone of Qiskit fails**: "unexpected disconnect while reading sideband packet", and the shallow clone
  dies silently.
- **No commit tarballs**: `codeload.github.com` returns 403.
- **No Rust**: no Rust toolchain (rustup download returns 403) and no cargo.
- **PyPI works**: wheels, sdists and pre-releases all install.
- **`api.github.com`**: reachable through web_fetch, but the unauthenticated core quota was exhausted (shared
  IP). github.com HTML pages work.
- **Test-method counts** (`def test_`):

  | version | transpiler | compiler | collected by pytest (ddt-expanded) |
  |---|---|---|---|
  | 2.2.3 | 104 files / 1623 | 2 files / 143 | 2679 (2620 pass, 52 skip, 7 fail) |
  | 2.5.2 | 113 files / 1872 | 144 | 7686 |
- **Runtime**: the full 2.2.3 slice took **~129 s serial** on 2 vCPUs (per-file loop); 2.2.2's took 122 s.
  Creating a venv and installing a wheel takes ~17 s. One targeted fix test takes ~1 s.
- **Pitfalls**:
  1. Run tests from a directory holding only `test/`, never from the unpacked sdist root, which would shadow
     the installed `qiskit` with uncompiled source.
  2. `pytest-xdist` aborts: ddt test names embed object addresses (`GenericBackendV2 object at 0x...`), so the
     workers collect different tests. Run serially, or use `stestr`.
  3. Some tests use `unittest.mock` without importing it. A harness `conftest.py` with `import unittest.mock`
     fixes this.
  4. `test_unitary_synthesis_plugin.py` has 7 environmental failures because its test plugins are registered
     only by a dev install (entry points). Exclude that file.
  5. Long background jobs were killed between tool calls (one job at 43%). The loop has to be resumable, per
     file (`/tmp/tools/slice.sh`).
  6. Disk is ~9.6 GB with ~290 MB per venv. Delete venvs between events.
  7. Hangs (C7) need `timeout`/`pytest-timeout`.
  8. The sandbox runs Python 3.10.

## 5. Cost per regression (estimates)

- **Sandbox, wheel pair** (C1, C2, C4–C9): ~5–10 min.
  - Covers 2 venvs, the sdist tests, the backported fix test, and the full slice on both sides.
  - 2.5.x is likely ~3× longer because of the bigger collection (not timed).
- **Windows PC with Rust** (`build_qiskit_event.ps1`): ~25–60 min per commit pair.
  - Covers 2 source builds of "several minutes" to roughly 15–25 min each (release build), plus 3–5 min of
    tests.
  - The first clone adds about 10 min.
  - Needed only for commit-exact attribution (C3 at `dd8269969`, C10, introduction-boundary SHAs for C4–C8).

## 6. Risks

- **Attribution**:
  - Wheel pairs bracket whole releases. Patch releases are small backport sets, so C1/C4/C5/C6/C7/C8 are clean.
  - C9's regression status is unproven.
- **Test drift**: at introduction boundaries, fix tests may encode later behaviour or API (C4, C5). Pre-register
  transplant rules and semantic variants.
- **Selection bias**: only bugs that got a regression test can be detected, so "detection" is near-tautological
  for the fix test. The study variable should be *which selection/prioritisation policy runs that test, and
  how early*, not whether it exists.
- **Flaky or environment-dependent faults**: C7 depends on threads, and determinism faults (#14730) are not
  test-detectable here.
- **Leftover TBDs**: SHAs for #15625, #15667, #14056 and the merge SHAs of the fixes. Resolve them with
  `git log --grep "(#NNNNN)"` on the PC.
