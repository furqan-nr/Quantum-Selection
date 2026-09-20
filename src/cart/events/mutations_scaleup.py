"""Scale-up mutation operators (EMSE scale-up, Phase A2 — PAPER2_EMSE_SCALEUP_PLAN.md).

DESIGN NOTE, pre-registered before any scale-up label is read (Decision 1 of the plan): earlier
drafts of this expansion considered creating 3 parameterized "instances" of each of the existing 9
operators (e.g. varying the injection site of insert_redundant_cx_pair). That approach was rejected
after reading METHODOLOGY §1.6, which already treats same-operator variants as non-independent
(`split_group_id = base_revision + mutation_family`) — three near-duplicate variants of one operator
would be pseudoreplication, not three independent fault instances, and would not survive review.

Every operator below is instead a genuinely distinct pass-manager transform, drawn from the same
four target-stage families already used in `mutations.py` (optimization, routing, layout,
translation) and the same permitted-mutation-type list in METHODOLOGY §1.5. Each one was empirically
verified against this corpus's actual four circuit families (ghz, qft, qaoa_linear,
random_clifford), at both optimization levels and both backends, before being included here:

  1. It must fire (produce a circuit structurally different from the unmutated baseline — different
     count_ops() or size()) on at least one manifest unit. Several plausible candidates turned out to
     be structurally dead for THIS corpus's clean, hand-built circuit families and were dropped:
     CommutativeCancellation, InverseCancellation, RemoveIdentityEquivalent, and Split2QUnitaries
     removal (no natural redundancy/2Q-unitary-block patterns in ghz/qft/qaoa_linear/random_clifford
     to act on), RemoveDiagonalGatesBeforeMeasure removal (the corpus's circuits are built with
     measured=False, so there is never a measurement to be diagonal-before), ContractIdleWiresInControlFlow
     removal (no control-flow ops in any family), and both HighLevelSynthesis removal and
     unitary_synthesis_method="sk" (no high-level-synthesizable objects or raw UnitaryGate blocks are
     ever present — every family is built from named primitive gates, see circuits.py). These are
     real, checked facts about this corpus, not assumptions.
  2. It must not hang. `routing_method="lookahead"` was dropped after it took >85s (still not
     finished) on qft/heavy_hex/opt=1 alone, versus <1s for every other candidate on every unit
     tested — a real risk to a Kaggle labeling run, caught here instead of mid-Phase-B.
  3. It must be semantics-preserving. Every operator kept below was checked with
     `Operator(...).equiv(...)` against its own baseline transpile, on all four circuit families —
     same requirement the existing 9 satisfy (§1.5: quality/performance faults only, not semantic).

This reached 10 genuinely distinct new operators, not the original aspirational 18. Combined with
the existing 9 in `mutations.py`, the scale-up mutation cohort is 19 events, not 27. This is reported
honestly in the manuscript as what rigorous verification supported, not padded to hit a round number
— see PAPER2_EMSE_SCALEUP_PLAN.md, "what could go wrong."

Kept separate from `mutations.py`'s `MUTATION_OPERATORS` registry so the primary frozen n=9 result
and its evaluate() path (`SELECTORS`, `MUTATION_OPERATORS`) are untouched by anything in this file.
"""
from __future__ import annotations

from typing import Any

from qiskit import QuantumCircuit
from qiskit.transpiler import PassManager, generate_preset_pass_manager

from cart.events.mutations import BaseConfig, MutationOperator, Transpiler
from cart.events.schema import FaultType


def _build_preset(cfg: BaseConfig):
    return generate_preset_pass_manager(**cfg)


def _remove_top_level_task(pm, stage: str, task_class_name: str) -> int:
    """Same mechanism as mutations.py's helper of the same name (duplicated, not imported, to keep
    this module fully independent of mutations.py's private helpers)."""
    sub = getattr(pm, stage)
    if not hasattr(sub, "_flatten_tasks"):
        raise RuntimeError("PassManager._flatten_tasks unavailable; pin within the 2.1-2.4 band.")
    flat = list(sub._flatten_tasks(sub._tasks))
    kept = [t for t in flat if type(t).__name__ != task_class_name]
    removed = len(flat) - len(kept)
    setattr(pm, stage, PassManager(kept))
    return removed


# ---- single-mechanism operators -----------------------------------------------------------

def _remove_consolidate_blocks(cfg: BaseConfig) -> Transpiler:
    """Omit ConsolidateBlocks (2Q-unitary-block consolidation before synthesis). Verified live only
    on random_clifford at optimization_level=3 (4/32 units in verification sweep) — a regime-specific
    fault by construction, consistent with METHODOLOGY's corpus design (§4.2/CORPUS_DESIGN_B1)."""
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "init", "ConsolidateBlocks")
    return pm.run


def _remove_elide_permutations(cfg: BaseConfig) -> Transpiler:
    """Omit ElidePermutations (SWAP-network elision). Verified live mainly on qft (its trailing SWAP
    network is exactly what this pass elides), 8/32 units in verification sweep."""
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "init", "ElidePermutations")
    return pm.run


def _remove_basis_translator(cfg: BaseConfig) -> Transpiler:
    """Omit BasisTranslator from the translation stage. Verified the output stays fully basis-compliant
    (no off-basis gate names appear — UnitarySynthesis/HighLevelSynthesis cover the gap) and remains
    unitarily equivalent to baseline on every family tested; it is a genuine quality regression (worse
    gate composition), not the functional failure that `_incomplete_basis_translation` in mutations.py
    produces via a different mechanism (restricting basis_gates itself). Broadest single new operator:
    16/32 units in verification sweep."""
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "translation", "BasisTranslator")
    return pm.run


def _downgrade_layout_dense(cfg: BaseConfig) -> Transpiler:
    """Force DenseLayout (a weaker, non-heuristic-informed layout method) in place of the
    optimization-level default (VF2Layout/SabreLayout). A third distinct layout degradation alongside
    the existing 9's `downgrade_layout_trivial` (trivial != dense: different algorithms, different
    failure signatures)."""
    mut = dict(cfg)
    mut["layout_method"] = "dense"
    return _build_preset(mut).run


def _downgrade_translation_synthesis(cfg: BaseConfig) -> Transpiler:
    """Force translation_method="synthesis" (unitary-synthesis-based basis translation) instead of the
    default equivalence-library-based BasisTranslator path. Verified live on every unit tested (5/5
    small sweep, reliable across families) — the most consistently-firing new operator."""
    mut = dict(cfg)
    mut["translation_method"] = "synthesis"
    return _build_preset(mut).run


def _seed_drift(cfg: BaseConfig) -> Transpiler:
    """A silently drifted transpiler seed: candidate uses seed_transpiler=9999 in place of the
    corpus's declared seed=1234, while remaining fully deterministic itself (same seed every run of
    THIS operator, so it does not reintroduce non-determinism into the labeling process). This mirrors
    a real historical fault class already in the corpus design (corpus_costhet.yaml
    detection_placement.determinism_14730_16237, and the verified hist-vf2layout-determinism-1q
    event) — a stochastic-pass seed regression, but expressed here as a controlled mutation rather
    than a historical fix boundary. Cross-cutting (affects layout and routing stage-selection
    together, not one stage), so classified target_stage="passmanager_global" per stage_map.yaml's
    own guidance that cross-cutting changes route to the exploration reserve rather than being
    artificially pinned to one stage. Verified live on 4/16 units in the small sweep (concentrated on
    random_clifford and qft/heavy_hex)."""
    mut = dict(cfg)
    mut["seed_transpiler"] = 9999
    return _build_preset(mut).run


def _insert_redundant_sx_quad(cfg: BaseConfig) -> Transpiler:
    """Post-transpile: append four SX gates on the first qubit. SX^4 = I (SX has order 4), so this is
    an identity insertion like the existing insert_redundant_cx_pair/insert_redundant_x_pair, but a
    genuinely different gate identity and magnitude (a single-qubit non-Pauli gate, 4 gates not 2) —
    kept to exactly one new operator in this family, deliberately not further parameterized, to avoid
    the same pseudoreplication risk this module's design note opens with."""
    run = _build_preset(cfg).run

    def transpile_fn(circuit: QuantumCircuit) -> QuantumCircuit:
        out = run(circuit)
        if out.num_qubits > 0:
            q = out.qubits[0]
            for _ in range(4):
                out.sx(q)
        return out

    return transpile_fn


# ---- compound operators (each pairs two already-verified-safe single mechanisms across a
# genuinely different pair of pass-manager stages — capped at one compound per stage-pair so these
# don't dilute into near-duplicates of each other; see the module design note) ------------------

def _combo_no_elide_synthesis_translate(cfg: BaseConfig) -> Transpiler:
    """(optimization, translation) compound: omit ElidePermutations AND force
    translation_method="synthesis". Verified live on every unit tested (32/32 in the broad sweep) —
    the two single mechanisms combine to fire far more broadly than either alone."""
    mut = dict(cfg)
    mut["translation_method"] = "synthesis"
    pm = _build_preset(mut)
    _remove_top_level_task(pm, "init", "ElidePermutations")
    return pm.run


def _combo_no_consolidate_dense_layout(cfg: BaseConfig) -> Transpiler:
    """(optimization, layout) compound: omit ConsolidateBlocks AND force layout_method="dense".
    Verified live on 20/32 units in the broad sweep — dense-layout's effect dominates, giving broad
    coverage across families that ConsolidateBlocks removal alone (random_clifford-only) never
    reaches on its own."""
    mut = dict(cfg)
    mut["layout_method"] = "dense"
    pm = _build_preset(mut)
    _remove_top_level_task(pm, "init", "ConsolidateBlocks")
    return pm.run


def _combo_dense_layout_basic_routing(cfg: BaseConfig) -> Transpiler:
    """(layout, routing) compound: force layout_method="dense" AND routing_method="basic". Reuses
    the existing 9's `downgrade_routing` knob value (routing_method="basic") deliberately, since it is
    already an established-safe, non-hanging choice (unlike routing_method="lookahead", dropped
    above) — the new element is the paired dense-layout perturbation, not a new routing value.
    Verified live on 20/32 units in the broad sweep."""
    mut = dict(cfg)
    mut["layout_method"] = "dense"
    mut["routing_method"] = "basic"
    return _build_preset(mut).run


MUTATION_OPERATORS_SCALEUP: dict[str, MutationOperator] = {
    op.family: op for op in [
        MutationOperator("remove_consolidate_blocks", FaultType.quality, "optimization",
                         "Omit ConsolidateBlocks (2Q-unitary-block consolidation before synthesis).",
                         _remove_consolidate_blocks),
        MutationOperator("remove_elide_permutations", FaultType.quality, "optimization",
                         "Omit ElidePermutations (SWAP-network elision).",
                         _remove_elide_permutations),
        MutationOperator("remove_basis_translator", FaultType.quality, "translation",
                         "Omit BasisTranslator from the translation stage (stays basis-compliant "
                         "via UnitarySynthesis/HighLevelSynthesis, worse gate composition).",
                         _remove_basis_translator),
        MutationOperator("downgrade_layout_dense", FaultType.quality, "layout",
                         "Force DenseLayout in place of the optimization-level default layout method.",
                         _downgrade_layout_dense),
        MutationOperator("downgrade_translation_synthesis", FaultType.quality, "translation",
                         "Force unitary-synthesis-based translation instead of BasisTranslator.",
                         _downgrade_translation_synthesis),
        MutationOperator("seed_drift", FaultType.quality, "passmanager_global",
                         "Silently drifted transpiler seed (9999 instead of the corpus's 1234), "
                         "deterministic per-event but cross-cutting across layout+routing.",
                         _seed_drift),
        MutationOperator("insert_redundant_sx_quad", FaultType.quality, "optimization",
                         "Append four redundant SX gates (SX^4 = I) on the first qubit.",
                         _insert_redundant_sx_quad),
        MutationOperator("combo_no_elide_synthesis_translate", FaultType.quality, "translation",
                         "Compound: omit ElidePermutations AND force synthesis-based translation.",
                         _combo_no_elide_synthesis_translate),
        MutationOperator("combo_no_consolidate_dense_layout", FaultType.quality, "layout",
                         "Compound: omit ConsolidateBlocks AND force DenseLayout.",
                         _combo_no_consolidate_dense_layout),
        MutationOperator("combo_dense_layout_basic_routing", FaultType.quality, "layout",
                         "Compound: force DenseLayout AND basic routing.",
                         _combo_dense_layout_basic_routing),
    ]
}


def get_operator_scaleup(family: str) -> MutationOperator:
    if family not in MUTATION_OPERATORS_SCALEUP:
        raise KeyError(f"unknown scale-up mutation family: {family!r}. "
                       f"Known: {sorted(MUTATION_OPERATORS_SCALEUP)}")
    return MUTATION_OPERATORS_SCALEUP[family]


# mutations.MUTATION_OPERATORS has 10 entries, not 9: it also carries `incomplete_basis_translation`,
# documented in mutations.py as a functional-fixture FALLBACK never instantiated as a ledger event
# (data/events/events.csv has exactly 9 "mut-*" rows, not 10). Any scale-up event-list builder must
# exclude it explicitly, so this constant makes the exclusion visible rather than implicit.
_NOT_COHORT_MEMBERS = frozenset({"incomplete_basis_translation"})


def scaleup_cohort_operators() -> dict[str, MutationOperator]:
    """The 9 operators actually instantiated as mutation-cohort events in the primary ledger
    (imported, not redefined) plus the 10 new ones here: exactly the 19-event scale-up cohort.
    Use this — not `all_scaleup_operators()` — when building the scale-up event list (Phase B1)."""
    from cart.events.mutations import MUTATION_OPERATORS
    cohort = {k: v for k, v in MUTATION_OPERATORS.items() if k not in _NOT_COHORT_MEMBERS}
    cohort.update(MUTATION_OPERATORS_SCALEUP)
    return cohort


def all_scaleup_operators() -> dict[str, MutationOperator]:
    """Every operator in both registries verbatim (10 original, including the non-cohort
    `incomplete_basis_translation` fallback, + 10 new = 20). General-purpose union; NOT what the
    scale-up event list should be built from — use `scaleup_cohort_operators()` for that."""
    from cart.events.mutations import MUTATION_OPERATORS
    combined: dict[str, Any] = dict(MUTATION_OPERATORS)
    combined.update(MUTATION_OPERATORS_SCALEUP)
    return combined
