"""Decomposed selector — diversity first, cost second, severity as tie-break only
(EMSE scale-up Phase A1 — PAPER2_EMSE_SCALEUP_PLAN.md).

Pre-registered before any scale-up label is read. Faithful to the mechanism diagnosed for the
primary frozen result (§6.4/§7 of the manuscript): the proposed `risk_score` selector's multiplicative
composite lets its severity term (`impact_prior`) outrank an already-cheap, already-detecting unit,
because severity, detectability, cost, and diversity are all multiplied into one score with no
priority order between them. `diversity_only` never makes that mistake because it never reasons about
severity at all.

This selector keeps diversity_only's exact greedy-coverage mechanism (never re-testing an already-seen
(circuit_family, backend_id) combination while any uncovered one remains affordable) and adds severity
only as a tie-break *within* an already-fixed diversity/cost ordering — never as a multiplicand that
can override it. Concretely, tests are ranked by the tuple:

    (already_covered: bool,   # False (new combo) sorts before True (seen combo) — diversity first
     baseline_cost:   float,  # cheaper sorts first among equal coverage status — cost second
     -severity:        float)  # higher severity breaks remaining ties only — severity last

`severity` reuses `proposed.CIRCUIT_CRITICALITY` and the same connectivity-pressure term as
`proposed._components`'s `impact_prior` (the manuscript's own severity proxy), deliberately NOT
`oracle_confidence` — severity and detectability are kept distinct per METHODOLOGY §4.1, and only
severity is the term diagnosed as the failure mechanism.

This module does not modify `baselines.py`, `proposed.py`, or `metrics/evaluate.py`'s primary
`SELECTORS` dict. It is wired into the scale-up evaluation only, via
`cart.selectors.registry_scaleup.SELECTORS_SCALEUP`.
"""
from __future__ import annotations

from functools import lru_cache

from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import expected_cost
from cart.selectors.proposed import CIRCUIT_CRITICALITY
from cart.features.connectivity import connectivity_pressure, two_qubit_density
from cart.manifest.circuits import build as build_circuit
from cart.manifest.backends import coupling_map_for


@lru_cache(maxsize=256)
def _pressure(family: str, n: int, backend: str) -> float:
    circ = build_circuit(family, n, seed=1234, measured=False)
    cmap = coupling_map_for(backend, n)
    pressure, _twoq = connectivity_pressure(circ, cmap), two_qubit_density(circ)
    return pressure


def _severity(ctx: SelectionContext, test_id: str) -> float:
    """Same severity proxy as proposed.py's impact_prior, minus the historical-failure-rate term
    (which is context/event-dependent and orthogonal to the diversity-first/cost-second/severity-
    tie-break structure being tested here) — circuit criticality x connectivity pressure only."""
    m = ctx.test_meta(test_id)
    pressure = _pressure(m.circuit_family, m.n_qubits, m.backend_id)
    return CIRCUIT_CRITICALITY.get(m.circuit_family, 1.0) * (1.0 + pressure)


def decomposed_selector(ctx: SelectionContext, event_id: str, budget_s: float, **_) -> list[str]:
    """Diversity first (greedy coverage of (circuit_family, backend_id)), cost second (cheapest
    among equal coverage status), severity only as a final tie-break. Never re-transpiles; ranks
    over cached SelectionContext metadata exactly like the five baselines and `proposed`."""
    ids = ctx.candidate_test_ids()
    seen_combo: set[tuple[str, str]] = set()
    chosen: list[str] = []
    spent = 0.0

    def combo(t: str) -> tuple[str, str]:
        m = ctx.test_meta(t)
        return (m.circuit_family, m.backend_id)

    remaining = list(ids)
    while remaining:
        def sort_key(t: str):
            already_covered = combo(t) in seen_combo
            cost = expected_cost(ctx, event_id, t)
            return (already_covered, cost, -_severity(ctx, t))

        remaining.sort(key=sort_key)
        picked = None
        for t in remaining:
            c = expected_cost(ctx, event_id, t)
            if spent + c <= budget_s:
                picked = t
                break
        if picked is None:
            break
        chosen.append(picked)
        spent += expected_cost(ctx, event_id, picked)
        seen_combo.add(combo(picked))
        remaining.remove(picked)

    return chosen
