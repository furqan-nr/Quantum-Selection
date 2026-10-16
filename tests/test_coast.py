"""Tests for Phase C: the COAST selector (cart.selectors.coast), its registry, and the Phase C mutation operators
(cart.events.mutations_phase_c). No ground-truth label is produced: operator tests transpile 5-qubit circuits only."""
import math

import pytest
from qiskit.quantum_info import Operator

from cart.events.schema import Event, FaultSource, FaultType, TrainOrTest
from cart.manifest.static_manifest import TestUnit
from cart.selectors.context import SelectionContext
from cart.selectors.coast import (AnalyticOracleModel, OracleCostEstimator, coast_costs, coast_selector,
                                  default_estimator, effective_oracle_tier, fit_analytic, speed_factor)


def _unit(tid, fam, backend, n=5, oracle="unitary", opt=1):
    return TestUnit(test_id=tid, circuit_family=fam, n_qubits=n, backend_id=backend,
                    transpiler_config_id=f"opt{opt}+basis", declared_pass_stages=("layout",), oracle_type=oracle)


def _event(eid="e"):
    return Event(event_id=eid, baseline_sha="b" * 12, candidate_sha="b" * 12, fault_id=f"f-{eid}",
                 fault_source=FaultSource.mutation, fault_type=FaultType.quality, event_environment_id="env",
                 split_group_id="x", event_date="2026-10-16", train_or_test=TrainOrTest.test,
                 change_metadata={"modified_pass_stages": ["layout"]}, mutation_family="x")


def _ctx(units, base=0.01, history=()):
    units = {u.test_id: u for u in units}
    return SelectionContext(units=units, events={"e": _event()},
                            baseline_costs={("e", t): base for t in units}, history=list(history))


def _est(prev, **kw):
    return OracleCostEstimator(prev_oracle_s=prev, analytic=AnalyticOracleModel(0.001, 1e-8, 0.0001, 1e-5), **kw)


# ------------------------------------------------------------------------------------------- oracle tier
def test_effective_oracle_tier_matches_engine_rule():
    assert effective_oracle_tier(_unit("a", "ghz", "line", 5)) == "exact"
    assert effective_oracle_tier(_unit("b", "ghz", "line", 12)) == "exact"
    assert effective_oracle_tier(_unit("c", "ghz", "heavy_hex", 5)) == "structural"     # ancillas (19-qubit map)
    assert effective_oracle_tier(_unit("d", "ghz", "line", 18, oracle="sampled_sv")) == "structural"


# ------------------------------------------------------------------------------------------- analytic model
def test_fit_analytic_recovers_parameters():
    rows = []
    for n, g in [(5, 10), (8, 40), (12, 100), (12, 600)]:
        rows.append(dict(tier="exact", n=n, g=g, oracle_s=0.002 + 5e-8 * g * 4 ** n))
    for g in [10, 1000, 50000]:
        rows.append(dict(tier="structural", n=40, g=g, oracle_s=1e-4 + 6e-6 * g))
    m = fit_analytic(rows)
    assert m.c0_exact == pytest.approx(min(r["oracle_s"] for r in rows if r["tier"] == "exact"))
    assert m.predict("exact", 12, 600) == pytest.approx(0.002 + 5e-8 * 600 * 4 ** 12, rel=0.05)
    assert m.predict("structural", 40, 50000) == pytest.approx(1e-4 + 6e-6 * 50000, rel=0.05)


def test_estimator_previous_then_analytic_fallback_and_speed():
    u_seen, u_new = _unit("seen", "qft", "line", 12), _unit("new", "qft", "line", 12)
    est = _est({"seen": 250.0}, out_size={"new": 600.0})
    assert est.source("seen") == "previous_session" and est.source("new") == "analytic"
    assert est.oracle_cost(u_seen) == 250.0
    assert est.oracle_cost(u_new) == pytest.approx(0.001 + 1e-8 * 600 * 4 ** 12)
    slow = _est({"seen": 250.0}, speed_factor=0.5)
    assert slow.oracle_cost(u_seen) == 125.0
    assert OracleCostEstimator.from_dict(est.to_dict()).oracle_cost(u_seen) == 250.0


def test_speed_factor_band():
    prev = {"a": 1.0, "b": 2.0, "c": 0.01}
    assert speed_factor({"a": 0.95, "b": 1.9, "c": 0.5}, prev) == (pytest.approx(0.95), 1.0)   # c ignored (< 0.05 s)
    k_raw, k = speed_factor({"a": 0.5, "b": 1.0}, prev)
    assert k_raw == pytest.approx(0.5) and k == pytest.approx(0.5)


# ------------------------------------------------------------------------------------------- selector
def test_coast_uses_oracle_aware_cost_not_constants():
    """A 12-qubit exact unit that is cheap to transpile but expensive to check must rank after a cheap unit
    of a NEW combo, and must not fit a budget that only its transpilation cost would fit."""
    units = [_unit("exp", "qft", "line", 12), _unit("cheap", "ghz", "line", 5)]
    est = _est({"exp": 250.0, "cheap": 0.003})
    ctx = _ctx(units)
    assert coast_selector(ctx, "e", math.inf, estimator=est) == ["cheap", "exp"]
    assert coast_selector(ctx, "e", 5.0, estimator=est) == ["cheap"]
    assert coast_costs(ctx, "e", est)["exp"] == pytest.approx(250.01)


def test_coast_diversity_first_then_cost_then_severity():
    units = [_unit("ghz_a", "ghz", "line"), _unit("ghz_b", "ghz", "line"),          # same combo
             _unit("qft_hh", "qft", "heavy_hex"), _unit("qaoa_l", "qaoa_linear", "line")]
    est = _est({t.test_id: 0.0 for t in units})
    rk = coast_selector(_ctx(units), "e", math.inf, estimator=est)
    # all costs equal: the three new combos come first, ordered by severity (qft 1.5 > qaoa 1.3 > ghz 1.0)
    assert rk[:3] == ["qft_hh", "qaoa_l", "ghz_a"] and rk[3] == "ghz_b"


def test_coast_tier_key_covers_exact_and_structural_separately():
    units = [_unit("ghz5", "ghz", "line", 5), _unit("ghz18", "ghz", "line", 18, oracle="sampled_sv"),
             _unit("ghz8", "ghz", "line", 8)]
    est = _est({"ghz5": 0.01, "ghz8": 0.02, "ghz18": 0.5})
    ctx = _ctx(units)
    assert coast_selector(ctx, "e", math.inf, estimator=est) == ["ghz5", "ghz18", "ghz8"]
    assert coast_selector(ctx, "e", math.inf, estimator=est, tier_key=False) == ["ghz5", "ghz8", "ghz18"]


def test_coast_respects_budget_in_estimated_seconds():
    units = [_unit(f"u{i}", fam, bk, n) for i, (fam, bk, n) in
             enumerate([("ghz", "line", 5), ("qft", "line", 8), ("qft", "line", 12), ("qaoa_linear", "heavy_hex", 5)])]
    est = _est({"u0": 0.01, "u1": 0.4, "u2": 260.0, "u3": 0.001})
    ctx = _ctx(units)
    cost = coast_costs(ctx, "e", est)
    for B in (0.0, 0.05, 0.5, 10.0, 300.0):
        ch = coast_selector(ctx, "e", B, estimator=est)
        assert sum(cost[t] for t in ch) <= B + 1e-12


def test_coast_ignores_history_and_labels():
    units = [_unit("a", "ghz", "line"), _unit("b", "qft", "line", 8)]
    est = _est({"a": 0.01, "b": 0.3})
    hist = [{"event_id": "old", "test_id": "b", "label": "quality_regression", "event_date": "2026-01-01"}]
    assert coast_selector(_ctx(units), "e", math.inf, estimator=est) == \
        coast_selector(_ctx(units, history=hist), "e", math.inf, estimator=est)


def test_registry_and_frozen_estimator():
    from cart.selectors.registry_phase_c import SELECTORS_PHASE_C
    from cart.selectors.registry_scaleup import SELECTORS_SCALEUP
    assert set(SELECTORS_PHASE_C) == set(SELECTORS_SCALEUP) | {"coast"}
    est = default_estimator()
    assert len(est.prev_oracle_s) == 116 and est.speed_factor == 1.0
    assert est.prev_oracle_s["random_clifford-n12-line-opt3"] > 100.0


# ------------------------------------------------------------------------------------------- Phase C operators
def _cfg(n, backend="line", opt=1):
    from cart.manifest.backends import coupling_map_for
    return dict(optimization_level=opt, coupling_map=coupling_map_for(backend, n),
                basis_gates=["cx", "rz", "sx", "x"], seed_transpiler=1234)


def test_phase_c_registry_shape():
    from cart.events.mutations_phase_c import MUTATION_OPERATORS_PHASE_C as OPS, get_operator_any
    assert len(OPS) == 10
    kinds = [op.fault_type for op in OPS.values()]
    assert kinds.count(FaultType.semantic) == 4 and kinds.count(FaultType.functional) == 1
    assert get_operator_any("drop_first_rzz").family == "drop_first_rzz"
    assert get_operator_any("seed_drift").family == "seed_drift"                      # scale-up registry
    assert get_operator_any("force_opt_level_0").family == "force_opt_level_0"        # primary registry


@pytest.mark.parametrize("family,circ_family,equivalent", [
    ("drop_first_rzz", "qaoa_linear", False), ("cp_small_angle_sign_flip", "qft", False),
    ("drop_routed_swap", "qft", False), ("cp_swap_detour", "qft", True)])
def test_phase_c_semantics_on_5_qubits(family, circ_family, equivalent):
    from cart.events.mutations_phase_c import MUTATION_OPERATORS_PHASE_C as OPS
    from cart.manifest.circuits import build
    c = build(circ_family, 5, seed=1234)
    out = OPS[family].transpiler(_cfg(5))(c)
    assert Operator(c).equiv(Operator.from_circuit(out)) is equivalent


def test_phase_c_input_gates_leave_other_inputs_untouched():
    from cart.events.mutations import baseline_transpiler
    from cart.events.mutations_phase_c import MUTATION_OPERATORS_PHASE_C as OPS
    from cart.manifest.circuits import build
    c = build("qft", 5, seed=1234)
    base = baseline_transpiler(_cfg(5))(c)
    for fam in ("wide_drop_opt_loop", "wide_rz_sign_flip", "wide_leaky_basis_h", "wide_no_elide_permutations"):
        assert OPS[fam].transpiler(_cfg(5))(c) == base, fam                          # width-gated: n = 5 untouched
    assert OPS["heavy_hex_trivial_layout"].transpiler(_cfg(5))(c) == base             # topology-gated: line untouched


# ------------------------------------------------------------------------------------------- frozen analysis (Phase C)
def _pca():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "scripts" / "phase_c_analysis.py"
    spec = importlib.util.spec_from_file_location("phase_c_analysis_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _cohort(suite_err=0.05, ape=0.05, spends=(0.9, 0.95)):
    budget = {}
    for tier in ("pr", "nightly"):
        budget[f"E_{tier}"] = {"previous": {n: {"spent_over_budget": None} for n in ("cheapest_first", "diversity_only")},
                               "own": {"coast": {"spent_over_budget": None}}}
    events = {}
    for i, sp in enumerate(spends):
        b = json_copy(budget)
        for tier in ("pr", "nightly"):
            for n in ("cheapest_first", "diversity_only"):
                b[f"E_{tier}"]["previous"][n]["spent_over_budget"] = sp
            b[f"E_{tier}"]["own"]["coast"]["spent_over_budget"] = sp
        events[f"e{i}"] = {"budget": b}
    return {"estimator_accuracy": {"suite_relative_error": suite_err, "expensive_median_ape": ape}, "events": events}


def json_copy(x):
    import json
    return json.loads(json.dumps(x))


def test_confirmatory_decision_rules():
    m = _pca()
    ok = m.confirmatory({"C1": _cohort(), "C2": _cohort()})
    assert ok["P1"]["supported"] and ok["P2"]["supported"]
    bad1 = m.confirmatory({"C1": _cohort(), "C2": _cohort(suite_err=-0.3)})        # cost transfer fails in C2 only
    assert not bad1["P1"]["supported"] and bad1["P1"]["failed_criteria"]["C2"] == ["suite_abs_error_le_0.25"]
    bad2 = m.confirmatory({"C1": _cohort(spends=(0.5, 2.1))})                       # mean 1.3 and one event > 2x
    assert not bad2["P2"]["supported"]
    assert m.confirmatory({})["P1"]["supported"] is False                            # no cohort -> nothing supported


def test_sign_test_minimum_p_and_holm():
    m = _pca()
    assert m.sign_one_sided(10, 0) == pytest.approx(2 ** -10)
    assert m.sign_one_sided(0, 0) == 1.0                                             # all ties -> uninformative
    adj = m.holm({"a": 2 ** -7, "b": 0.03, "c": 0.04, "d": 0.2})
    assert adj["a"] == pytest.approx(4 * 2 ** -7) and adj["d"] == pytest.approx(0.2)
    assert m.perm_one_sided([0.0, 0.0]) == 1.0
