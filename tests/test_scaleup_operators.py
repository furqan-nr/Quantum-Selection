"""Structural tests for the scale-up mutation operators (EMSE scale-up Phase A2/A4).

These check that each new operator builds without error and produces output that differs from an
unmutated baseline transpile on at least one manifest circuit family/config combination — i.e. each
operator is "live," not dead weight. This mirrors the empirical verification already done ad hoc
(see mutations_scaleup.py's module docstring) but locks it in as a regression test, and deliberately
does NOT touch the oracle, labeling, or cost machinery — no ground-truth run happens here, so nothing
in this file reads or produces a detection label. That distinction is what keeps this test
compatible with the pre-registration discipline (PAPER2_EMSE_SCALEUP_PLAN.md Phase A2): confirming a
mutation is structurally live is not the same as reading a detection outcome.
"""
from qiskit.transpiler import generate_preset_pass_manager
from qiskit.quantum_info import Operator

from cart.events.mutations_scaleup import (
    MUTATION_OPERATORS_SCALEUP, scaleup_cohort_operators, all_scaleup_operators,
)
from cart.manifest.backends import coupling_map_for
from cart.manifest.circuits import build as build_circuit

BASIS = ["cx", "rz", "sx", "x"]
# small, fast probe grid; empirical verification (module docstring) used a broader sweep before
# any of these operators were locked in — this is a lighter regression check, not the original audit
PROBE_UNITS = [
    ("ghz", 8, "line", 1), ("ghz", 8, "heavy_hex", 3),
    ("qft", 8, "line", 3), ("qft", 8, "heavy_hex", 3),
    ("qaoa_linear", 8, "line", 1),
    ("random_clifford", 8, "heavy_hex", 3),
    # seed_drift's known-firing combos (from the ad hoc verification sweep in
    # mutations_scaleup.py's docstring) — without these, seed_drift never fires on a probe grid
    # this small, which would be a false "dead weight" failure, not a real one
    ("random_clifford", 8, "line", 1), ("random_clifford", 8, "line", 3),
]


def _cfg(n, backend, opt):
    return dict(optimization_level=opt, coupling_map=coupling_map_for(backend, n),
                basis_gates=list(BASIS), seed_transpiler=1234)


def test_registry_has_exactly_ten_new_operators():
    assert len(MUTATION_OPERATORS_SCALEUP) == 10, sorted(MUTATION_OPERATORS_SCALEUP)


def test_scaleup_cohort_is_nineteen_and_excludes_the_functional_fallback():
    cohort = scaleup_cohort_operators()
    assert len(cohort) == 19
    assert "incomplete_basis_translation" not in cohort, (
        "incomplete_basis_translation is a functional-fixture fallback, never a ledger cohort "
        "member (see mutations_scaleup.py) — it must not leak into the scale-up event list"
    )


def test_all_scaleup_operators_includes_the_fallback():
    # sanity check the *other* helper's documented, different behavior, so the two don't silently
    # drift into meaning the same thing
    assert len(all_scaleup_operators()) == 20
    assert "incomplete_basis_translation" in all_scaleup_operators()


def test_every_new_operator_builds_without_error():
    for family, op in MUTATION_OPERATORS_SCALEUP.items():
        for fam, n, backend, opt in PROBE_UNITS[:1]:   # one cheap smoke unit is enough to confirm buildability
            cfg = _cfg(n, backend, opt)
            transpiler = op.transpiler(cfg)
            circ = build_circuit(fam, n, seed=1234, measured=False)
            out = transpiler(circ)
            assert out is not None, f"{family} produced no output on {fam}/{n}/{backend}/opt{opt}"


def test_every_new_operator_fires_on_at_least_one_probe_unit():
    """'Fires' = produces a circuit structurally different (count_ops/size) from the unmutated
    baseline on at least one of the probe units. An operator that never fires here is dead weight in
    the scale-up cohort — this is exactly the check the plan's 'flag early' risk item calls for."""
    dead = []
    for family, op in MUTATION_OPERATORS_SCALEUP.items():
        fired = False
        for fam, n, backend, opt in PROBE_UNITS:
            cfg = _cfg(n, backend, opt)
            circ = build_circuit(fam, n, seed=1234, measured=False)
            baseline_out = generate_preset_pass_manager(**cfg).run(circ)
            mut_out = op.transpiler(cfg)(circ)
            if baseline_out.count_ops() != mut_out.count_ops() or baseline_out.size() != mut_out.size():
                fired = True
                break
        if not fired:
            dead.append(family)
    assert not dead, f"operators that never fired on the probe grid (dead weight): {dead}"


def test_every_new_operator_is_semantics_preserving():
    """Unitary-equivalence check against baseline, on the 'line' backend (physical qubit count ==
    logical qubit count there, unlike heavy_hex which pads to a larger patch — see
    PAPER2_EMSE_SCALEUP_PLAN.md verification notes) at a small width for speed."""
    n, backend, opt = 8, "line", 3
    cfg = _cfg(n, backend, opt)
    for family, op in MUTATION_OPERATORS_SCALEUP.items():
        for fam in ["ghz", "qft", "qaoa_linear", "random_clifford"]:
            circ = build_circuit(fam, n, seed=1234, measured=False)
            baseline_out = generate_preset_pass_manager(**cfg).run(circ)
            mut_out = op.transpiler(cfg)(circ)
            equiv = Operator.from_circuit(baseline_out).equiv(Operator.from_circuit(mut_out))
            assert equiv, f"{family} broke semantic equivalence on {fam} (n={n}, {backend}, opt{opt})"
