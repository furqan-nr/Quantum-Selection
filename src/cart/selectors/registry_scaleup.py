"""Scale-up selector registry (EMSE scale-up Phase A3 — PAPER2_EMSE_SCALEUP_PLAN.md).

`SELECTORS_SCALEUP` extends `cart.metrics.evaluate.SELECTORS` (the five baselines + `proposed`) with
`decomposed`. This module does not modify `metrics/evaluate.py`'s own `SELECTORS`/`DETERMINISTIC`
constants or `gates/validity.py`'s own `SELECTORS` constant — those stay exactly as they are, so the
primary frozen n=9 result's evaluate()/run_all_gates() calls (which default to their own module-level
SELECTORS) are completely unaffected by anything in this file.

Usage (Phase C):
    from cart.metrics.evaluate import evaluate
    from cart.gates.validity import run_all_gates
    from cart.selectors.registry_scaleup import SELECTORS_SCALEUP

    report = evaluate(data_dir="data_scaleup", selectors=SELECTORS_SCALEUP, ...)
    gates = run_all_gates(data_dir="data_scaleup", selectors=SELECTORS_SCALEUP)
"""
from __future__ import annotations

from cart.metrics.evaluate import SELECTORS
from cart.selectors.decomposed import decomposed_selector

SELECTORS_SCALEUP: dict = {**SELECTORS, "decomposed": decomposed_selector}
