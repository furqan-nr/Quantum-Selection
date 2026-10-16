"""Phase C selector registry (PREREGISTRATION_PHASE_C.md).

`SELECTORS_PHASE_C` = `registry_scaleup.SELECTORS_SCALEUP` (five baselines + proposed + decomposed) plus
`coast` (cart.selectors.coast.coast_selector with the FROZEN Phase C estimator, configs/phase_c_cost_model.json).
No existing registry, selector or evaluate() default is modified by this module.
"""
from __future__ import annotations

from cart.selectors.coast import coast_selector
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP

SELECTORS_PHASE_C: dict = {**SELECTORS_SCALEUP, "coast": coast_selector}
