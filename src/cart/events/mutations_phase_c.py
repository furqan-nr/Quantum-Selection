"""Phase C mutation operators: fine-grained, input-specific faults (PREREGISTRATION_PHASE_C.md).

Why a third operator set. The manuscript's mutation cohorts (``mutations.py``, 9 operators, and
``mutations_scaleup.py``, 10 more) are COARSE: most operators degrade every output they touch (whole
optimization stage removed, whole optimization level lowered, a gate pair appended to every output), so
the cheapest units already expose most faults and every cost-aware order reaches the same detection
ceiling. They are also all semantics-preserving, so the exact unitary oracle never has to do work that
only it can do. Phase C replaces them, for confirmation, with ten operators that are

  * INPUT-SPECIFIC: the fault is only reachable for some inputs (a width threshold, one coupling-map
    topology, one gate type, one routing or translation decision), which is how real transpiler
    regressions usually present (a code path taken only for wide circuits, a topology-specific
    heuristic, a single rewrite rule); and
  * partly SEMANTICS- or STRUCTURE-BREAKING (5 of 10): four operators change the implemented unitary and can only be
    exposed by the exact unitary oracle (n <= 12, ancilla-free, i.e. the line-topology units of this
    corpus), and one makes the output structurally invalid (an out-of-basis gate) so that only the
    structural oracle (wide units) can expose it.

Mechanisms. Every operator is a deterministic transform of the preset pass manager produced by
``generate_preset_pass_manager`` (Qiskit 2.2.3 and 2.4.2 both verified, see PREREGISTRATION_PHASE_C.md
section 4): either a knob change, the insertion of one small custom pass at the START of a stage (a
top-level task, so no nested flow controller is touched), or the removal of a top-level task. Input
gating (width / topology) is decided from the input circuit's width and the unit's coupling map, both
pre-execution facts of the unit. Custom passes act on at most a handful of DAG nodes and terminate in
linear time.

Pass-manager facts used (verified on Qiskit 2.4.2 and 2.2.3 for this corpus): at optimization levels 1
and 3 SabreLayout already inserts the routing SWAPs in the LAYOUT stage, so SWAP, CP and RZZ gates all
survive unchanged to the start of the TRANSLATION stage; the final single-qubit RZ gates exist only after
translation/optimization.

Detection notes (labeling engine unchanged): an event is detected by a unit iff the unit's label equals
``LABEL_FOR_FAULT[fault_type]``. The four semantic operators can only be labelled ``semantic_fail`` on
exact-oracle units (the 24 line units with n <= 12; heavy-hex maps add ancillas, so those units fall to the
structural tier). The functional operator can only be labelled ``functional_fail`` by the structural oracle
(out-of-basis gate), i.e. on structural-tier units.

Kept separate from ``mutations.py`` / ``mutations_scaleup.py``; nothing there is modified.
"""
from __future__ import annotations

import math
from typing import Any

from qiskit import QuantumCircuit
from qiskit.circuit.library import CPhaseGate, RZGate, SwapGate
from qiskit.converters import circuit_to_dag
from qiskit.transpiler import CouplingMap, PassManager, generate_preset_pass_manager
from qiskit.transpiler.basepasses import TransformationPass

from cart.events.mutations import BaseConfig, MutationOperator, Transpiler
from cart.events.schema import FaultType

# ------------------------------------------------------------------------------------------ constants
# Pre-declared input gates (fixed before any Phase C label exists).
WIDE_OPT_LOOP_MIN_QUBITS = 27      # op 1: optimization loop skipped only for inputs with >= 27 qubits
SMALL_OPT_LOOP_MAX_QUBITS = 12     # op 3: optimization loop skipped only for inputs with <= 12 qubits
RZ_FLIP_MIN_QUBITS = 10            # op 7: RZ sign flip only for inputs with >= 10 qubits
LEAKY_BASIS_MIN_QUBITS = 40        # op 10: 'h' leaks into the target basis only for inputs >= 40 qubits
WIDE_ELIDE_MIN_QUBITS = 18         # op 5: ElidePermutations skipped only for inputs with >= 18 qubits
SMALL_CP_ANGLE = math.pi / 8       # op 6: |theta| <= pi/8 is the "small-angle" rewrite branch
_EPS = 1e-9


def _build_preset(cfg: BaseConfig):
    return generate_preset_pass_manager(**cfg)


def _stage_tasks(pm, stage: str) -> list:
    sub = getattr(pm, stage)
    if not hasattr(sub, "_flatten_tasks"):
        raise RuntimeError("PassManager._flatten_tasks unavailable; verified for Qiskit 2.2-2.4 only.")
    return list(sub._flatten_tasks(sub._tasks))


def _prepend_to_stage(pm, stage: str, pass_) -> None:
    setattr(pm, stage, PassManager([pass_] + _stage_tasks(pm, stage)))


def _remove_top_level_task(pm, stage: str, task_class_name: str) -> int:
    flat = _stage_tasks(pm, stage)
    kept = [t for t in flat if type(t).__name__ != task_class_name]
    setattr(pm, stage, PassManager(kept))
    return len(flat) - len(kept)


def is_heavy_hex(cmap: CouplingMap | None) -> bool:
    """Topology test from the coupling map alone: heavy-hex lattices have degree-3 nodes, a line never
    does (max degree 2). Pre-execution fact of the unit."""
    if cmap is None:
        return False
    deg: dict[int, set] = {}
    for a, b in cmap.get_edges():
        deg.setdefault(a, set()).add(b)
        deg.setdefault(b, set()).add(a)
    return any(len(v) >= 3 for v in deg.values())


def _gated(threshold: int, mutated_run, baseline_run) -> Transpiler:
    """Width-gated fault: the mutated code path is taken only for inputs with >= threshold qubits."""

    def transpile_fn(circuit: QuantumCircuit) -> QuantumCircuit:
        return (mutated_run if circuit.num_qubits >= threshold else baseline_run)(circuit)

    return transpile_fn


def _angle(node) -> float | None:
    try:
        return float(node.op.params[0])
    except (TypeError, ValueError, IndexError):
        return None


# ------------------------------------------------------------------------------------------ custom passes
class _FlipSmallCPhaseAngles(TransformationPass):
    """Broken small-angle branch of a controlled-phase rewrite: every CP(theta) with |theta| <= pi/8 is
    emitted as CP(-theta). Semantics-breaking for any circuit holding such a gate (QFT with n >= 4)."""

    def run(self, dag):
        for node in list(dag.op_nodes()):
            if node.op.name == "cp":
                th = _angle(node)
                if th is not None and 0 < abs(th) <= SMALL_CP_ANGLE + _EPS:
                    dag.substitute_node(node, CPhaseGate(-th))
        return dag


class _FlipFirstRZSign(TransformationPass):
    """One optimization rewrite emits RZ(-theta) for RZ(theta): the FIRST RZ (topological order) whose
    angle is not a multiple of pi (a multiple of pi would only change the global phase) is negated."""

    def run(self, dag):
        for node in dag.topological_op_nodes():
            if node.op.name == "rz":
                th = _angle(node)
                if th is None:
                    continue
                k = th / math.pi
                if abs(k - round(k)) > 1e-6:
                    dag.substitute_node(node, RZGate(-th))
                    break
        return dag


class _DropFirstSwap(TransformationPass):
    """One routing decision lost: the FIRST SWAP of the routed circuit is dropped before translation,
    while the layout bookkeeping still assumes it happened. Semantics-breaking; connectivity stays
    valid, so only the exact (layout-normalised) unitary oracle can expose it."""

    def run(self, dag):
        for node in dag.topological_op_nodes():
            if node.op.name == "swap":
                dag.remove_op_node(node)
                break
        return dag


class _DropFirstRZZ(TransformationPass):
    """Basis translation of RZZ silently emits nothing for the FIRST RZZ gate it meets (one dropped
    gate for one gate type). Semantics-breaking on circuits holding RZZ (QAOA)."""

    def run(self, dag):
        for node in dag.topological_op_nodes():
            if node.op.name == "rzz":
                dag.remove_op_node(node)
                break
        return dag


class _CPhaseSwapDetour(TransformationPass):
    """One translation decision degraded: the FIRST CP gate is emitted as SWAP . CP . SWAP on the same
    (adjacent) pair. CP is symmetric, so this is semantically exact but costs 6 extra CX; a quality fault
    whose relative size (+6 CX) only crosses the 10% 2Q threshold on small CP-holding circuits."""

    def run(self, dag):
        for node in dag.topological_op_nodes():
            if node.op.name == "cp":
                th = _angle(node)
                if th is None:
                    continue
                sub = QuantumCircuit(2)
                sub.append(SwapGate(), [0, 1])
                sub.append(CPhaseGate(th), [0, 1])
                sub.append(SwapGate(), [0, 1])
                dag.substitute_node_with_dag(node, circuit_to_dag(sub))
                break
        return dag


# ------------------------------------------------------------------------------------------ operator builders
def _wide_drop_opt_loop(cfg: BaseConfig) -> Transpiler:
    """Quality (optimization): the iterative optimization loop (top-level DoWhileController) is skipped
    only for inputs with >= 27 qubits (a size-dependent code path), cf. the coarse
    disable_optimization_loop operator, which hits every input."""
    base = _build_preset(cfg).run
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "optimization", "DoWhileController")
    return _gated(WIDE_OPT_LOOP_MIN_QUBITS, pm.run, base)


def _heavy_hex_trivial_layout(cfg: BaseConfig) -> Transpiler:
    """Quality (layout): a topology-specific layout regression; trivial layout is used ONLY when the
    coupling map is heavy-hex. Line-topology units are untouched."""
    if not is_heavy_hex(cfg.get("coupling_map")):
        return _build_preset(cfg).run
    mut = dict(cfg)
    mut["layout_method"] = "trivial"
    return _build_preset(mut).run


def _small_drop_opt_loop(cfg: BaseConfig) -> Transpiler:
    """Quality (optimization): a "small-circuit fast path" skips the iterative optimization loop
    (top-level DoWhileController) only for inputs with <= 12 qubits; the mirror image of
    wide_drop_opt_loop. (Two earlier candidates for this slot were dropped before any label existed:
    'basic' routing on wide line inputs emits 0.5-1M two-qubit gates on qft-n100/n127 and exhausts the
    3 GB labeling machine, and DenseLayout on wide line inputs changed 18 outputs but never crossed the
    pre-declared quality thresholds, i.e. it would be an unobservable quality fault by construction.)"""
    base = _build_preset(cfg).run
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "optimization", "DoWhileController")

    def transpile_fn(circuit: QuantumCircuit) -> QuantumCircuit:
        return (pm.run if circuit.num_qubits <= SMALL_OPT_LOOP_MAX_QUBITS else base)(circuit)

    return transpile_fn


def _cp_swap_detour(cfg: BaseConfig) -> Transpiler:
    """Quality (translation): one CP translation decision degraded (SWAP . CP . SWAP)."""
    pm = _build_preset(cfg)
    _prepend_to_stage(pm, "translation", _CPhaseSwapDetour())
    return pm.run


def _wide_no_elide_permutations(cfg: BaseConfig) -> Transpiler:
    """Quality (optimization, opt level 3): SWAP-network elision (ElidePermutations, init stage) is skipped
    only for inputs with >= 18 qubits; finer than the scale-up's remove_elide_permutations, which hit every
    width. (Replaces a first candidate, VF2PostLayout removal on heavy-hex maps, which crashed the opt-3
    pipeline with a KeyError and was therefore dropped as a functional, not quality, fault.)"""
    base = _build_preset(cfg).run
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "init", "ElidePermutations")
    return _gated(WIDE_ELIDE_MIN_QUBITS, pm.run, base)


def _cp_small_angle_sign_flip(cfg: BaseConfig) -> Transpiler:
    """Semantic (translation): small-angle CP rewrite branch negates the angle."""
    pm = _build_preset(cfg)
    _prepend_to_stage(pm, "translation", _FlipSmallCPhaseAngles())
    return pm.run


def _wide_rz_sign_flip(cfg: BaseConfig) -> Transpiler:
    """Semantic (optimization): one RZ angle sign flipped after optimization, only for inputs with >= 10
    qubits. In this corpus the exact oracle can see it only on the n = 12 line units, which are also the
    most expensive units to check (deliberately hard for cost-aware ordering)."""
    base = _build_preset(cfg).run
    pm = _build_preset(cfg)
    pm.optimization = PassManager(_stage_tasks(pm, "optimization") + [_FlipFirstRZSign()])
    return _gated(RZ_FLIP_MIN_QUBITS, pm.run, base)


def _drop_routed_swap(cfg: BaseConfig) -> Transpiler:
    """Semantic (routing): the first SWAP of the routed circuit is lost."""
    pm = _build_preset(cfg)
    _prepend_to_stage(pm, "translation", _DropFirstSwap())
    return pm.run


def _drop_first_rzz(cfg: BaseConfig) -> Transpiler:
    """Semantic (translation): the first RZZ gate is dropped during translation."""
    pm = _build_preset(cfg)
    _prepend_to_stage(pm, "translation", _DropFirstRZZ())
    return pm.run


def _wide_leaky_basis_h(cfg: BaseConfig) -> Transpiler:
    """Functional / structural (translation): for inputs with >= 40 qubits the translation target
    wrongly accepts 'h' as native, so H gates survive in the output. Unitarily exact, but the output is
    out of the unit's declared basis {cx, rz, sx, x}: only the structural oracle can expose it."""
    base = _build_preset(cfg).run
    mut = dict(cfg)
    mut["basis_gates"] = list(cfg["basis_gates"]) + ["h"]
    return _gated(LEAKY_BASIS_MIN_QUBITS, _build_preset(mut).run, base)


MUTATION_OPERATORS_PHASE_C: dict[str, MutationOperator] = {
    op.family: op for op in [
        # ---- quality, input-specific (5)
        MutationOperator("wide_drop_opt_loop", FaultType.quality, "optimization",
                         f"Optimization loop skipped only for inputs with >= {WIDE_OPT_LOOP_MIN_QUBITS} qubits.",
                         _wide_drop_opt_loop),
        MutationOperator("heavy_hex_trivial_layout", FaultType.quality, "layout",
                         "Trivial layout used only on heavy-hex coupling maps.",
                         _heavy_hex_trivial_layout),
        MutationOperator("small_drop_opt_loop", FaultType.quality, "optimization",
                         f"Optimization loop skipped only for inputs with <= {SMALL_OPT_LOOP_MAX_QUBITS} qubits.",
                         _small_drop_opt_loop),
        MutationOperator("cp_swap_detour", FaultType.quality, "translation",
                         "First CP gate translated as SWAP.CP.SWAP (+6 CX, exact).",
                         _cp_swap_detour),
        MutationOperator("wide_no_elide_permutations", FaultType.quality, "optimization",
                         f"SWAP-network elision skipped only for inputs with >= {WIDE_ELIDE_MIN_QUBITS} qubits (opt level 3).",
                         _wide_no_elide_permutations),
        # ---- semantics-breaking, exact-oracle detectable (4)
        MutationOperator("cp_small_angle_sign_flip", FaultType.semantic, "translation",
                         "CP(theta) with |theta| <= pi/8 emitted as CP(-theta).",
                         _cp_small_angle_sign_flip),
        MutationOperator("wide_rz_sign_flip", FaultType.semantic, "optimization",
                         f"First non-trivial RZ angle negated after optimization, inputs >= {RZ_FLIP_MIN_QUBITS} qubits.",
                         _wide_rz_sign_flip),
        MutationOperator("drop_routed_swap", FaultType.semantic, "routing",
                         "First SWAP of the routed circuit dropped before translation.",
                         _drop_routed_swap),
        MutationOperator("drop_first_rzz", FaultType.semantic, "translation",
                         "First RZZ gate dropped during translation.",
                         _drop_first_rzz),
        # ---- structurally invalid output, structural-oracle detectable (1)
        MutationOperator("wide_leaky_basis_h", FaultType.functional, "translation",
                         f"'h' leaks into the target basis for inputs >= {LEAKY_BASIS_MIN_QUBITS} qubits (out-of-basis output).",
                         _wide_leaky_basis_h),
    ]
}


def get_operator_phase_c(family: str) -> MutationOperator:
    if family not in MUTATION_OPERATORS_PHASE_C:
        raise KeyError(f"unknown Phase C mutation family: {family!r}. Known: {sorted(MUTATION_OPERATORS_PHASE_C)}")
    return MUTATION_OPERATORS_PHASE_C[family]


def get_operator_any(family: str) -> MutationOperator:
    """Lookup across all three registries (primary, scale-up, Phase C), for the Phase C labeling wrapper
    (scripts/run_phase_c_ground_truth.py), which patches cart.labels.ground_truth's lookup at run time
    instead of editing it."""
    if family in MUTATION_OPERATORS_PHASE_C:
        return MUTATION_OPERATORS_PHASE_C[family]
    from cart.events.mutations import MUTATION_OPERATORS
    if family in MUTATION_OPERATORS:
        return MUTATION_OPERATORS[family]
    from cart.events.mutations_scaleup import get_operator_scaleup
    return get_operator_scaleup(family)


def phase_c_metadata() -> dict[str, Any]:
    return {"wide_opt_loop_min_qubits": WIDE_OPT_LOOP_MIN_QUBITS,
            "small_opt_loop_max_qubits": SMALL_OPT_LOOP_MAX_QUBITS,
            "rz_flip_min_qubits": RZ_FLIP_MIN_QUBITS, "leaky_basis_min_qubits": LEAKY_BASIS_MIN_QUBITS,
            "wide_elide_min_qubits": WIDE_ELIDE_MIN_QUBITS,
            "small_cp_angle": SMALL_CP_ANGLE}
