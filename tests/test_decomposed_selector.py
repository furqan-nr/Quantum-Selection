"""Tests for the decomposed selector (EMSE scale-up Phase A1/A4).

Fixture style matches tests/test_phase3.py (the existing baseline-selector tests) so this can sit
alongside them without introducing a new pattern.
"""
from cart.events.schema import Event, FaultSource, FaultType, TrainOrTest
from cart.manifest.static_manifest import TestUnit
from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import expected_cost
from cart.selectors.decomposed import decomposed_selector


def _unit(tid, fam, backend, stages, oracle="unitary", n=5):
    return TestUnit(test_id=tid, circuit_family=fam, n_qubits=n, backend_id=backend,
                    transpiler_config_id="opt1+basis", declared_pass_stages=tuple(stages),
                    oracle_type=oracle)


def _event(eid, date, modified_stages, fault_type=FaultType.quality):
    return Event(event_id=eid, baseline_sha="b" * 12, candidate_sha="b" * 12, fault_id=f"f-{eid}",
                 fault_source=FaultSource.mutation, fault_type=fault_type,
                 event_environment_id="env", split_group_id="b" * 12 + "+x",
                 event_date=date, train_or_test=TrainOrTest.test,
                 change_metadata={"modified_pass_stages": modified_stages}, mutation_family="x")


def _ctx_tiebreak():
    """Four units, all equal cost. t_a and t_b share a (circuit_family, backend) combo; t_c and t_d
    are each the sole representative of their own combo. This isolates all three precedence levels:
    diversity (t_a/t_c/t_d are each a "new" combo the first time any of them is picked, t_b never is),
    cost (all tied here, so it never decides anything in this fixture), and severity as the tie-break
    among the new-combo candidates (CIRCUIT_CRITICALITY: qft=1.5 > qaoa_linear=1.3 > ghz=1.0)."""
    units = {
        "t_a": _unit("t_a", "ghz", "line", ["layout"]),
        "t_b": _unit("t_b", "ghz", "line", ["layout"]),          # same combo as t_a
        "t_c": _unit("t_c", "qft", "heavy_hex", ["optimization"]),
        "t_d": _unit("t_d", "qaoa_linear", "line", ["routing"]),
    }
    events = {"e_now": _event("e_now", "2026-06-12", ["optimization"])}
    baseline_costs = {("e_now", t): 0.10 for t in units}
    return SelectionContext(units=units, events=events, baseline_costs=baseline_costs, history=[])


def test_diversity_before_severity():
    """With cost tied, a new (family, backend) combo is always picked before a repeat of an
    already-seen combo, regardless of severity — diversity strictly outranks severity."""
    ctx = _ctx_tiebreak()
    sel = decomposed_selector(ctx, "e_now", budget_s=10.0)
    assert set(sel) == {"t_a", "t_b", "t_c", "t_d"}
    # t_b (repeat combo) must come after all three new-combo picks (t_a, t_c, t_d), in whatever
    # order those three land relative to each other.
    assert sel.index("t_b") == 3, f"t_b should be picked last (repeat combo); got order {sel}"


def test_severity_breaks_ties_among_new_combos():
    """Among candidates that are each a genuinely new combo and tied on cost, higher severity
    (CIRCUIT_CRITICALITY) wins the tie: qft (1.5) before qaoa_linear (1.3) before ghz (1.0)."""
    ctx = _ctx_tiebreak()
    sel = decomposed_selector(ctx, "e_now", budget_s=10.0)
    first_three = sel[:3]
    assert first_three.index("t_c") < first_three.index("t_d") < first_three.index("t_a"), (
        f"expected qft(t_c) < qaoa_linear(t_d) < ghz(t_a) by severity tie-break; got {sel}"
    )


def test_cost_beats_severity_among_equal_diversity_status():
    """When two new-combo candidates differ in cost, the cheaper one is picked first even if it has
    lower severity than the pricier one — cost strictly outranks severity (only diversity outranks
    cost)."""
    units = {
        "cheap_low_severity": _unit("cheap_low_severity", "ghz", "line", ["layout"]),        # severity 1.0
        "pricey_high_severity": _unit("pricey_high_severity", "qft", "heavy_hex", ["optimization"]),  # severity 1.5
    }
    events = {"e_now": _event("e_now", "2026-06-12", ["optimization"])}
    baseline_costs = {("e_now", "cheap_low_severity"): 0.05, ("e_now", "pricey_high_severity"): 0.50}
    ctx = SelectionContext(units=units, events=events, baseline_costs=baseline_costs, history=[])
    sel = decomposed_selector(ctx, "e_now", budget_s=10.0)
    assert sel[0] == "cheap_low_severity", f"cheaper new-combo candidate should win despite lower severity; got {sel}"


def test_respects_budget():
    ctx = _ctx_tiebreak()
    # each unit's expected_cost is baseline_cost(0.10) + oracle_cost(0.05, unitary tier) = 0.15;
    # 0.20 comfortably fits exactly one unit and not two (headroom avoids a float-boundary flake,
    # matching the existing baseline tests' convention, e.g. test_phase3's budget_s=0.20 case)
    budget = 0.20
    sel = decomposed_selector(ctx, "e_now", budget_s=budget)
    spent = sum(expected_cost(ctx, "e_now", t) for t in sel)
    assert spent <= budget + 1e-9
    assert len(sel) == 1


def test_zero_budget_selects_nothing():
    ctx = _ctx_tiebreak()
    assert decomposed_selector(ctx, "e_now", budget_s=0.0) == []
