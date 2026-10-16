"""COAST: Cost-calibrated, Oracle-Aware Selection for Transpiler tests (Phase C, PREREGISTRATION_PHASE_C.md).

What it does (and nothing more):

  1. ESTIMATE each unit's real CI cost before running anything:
         cost(u) = baseline transpilation cost of u (ctx.baseline_cost, the pre-execution baseline profile)
                 + estimated ORACLE cost of u,
     where the oracle estimate is the unit's mean measured oracle cost in EARLIER labeling sessions
     (``PreviousSessionOracle``) and, for a unit never measured before, a transparent analytic model
     (``AnalyticOracleModel``): exact-unitary tier  c = c0 + theta * G * 4^n,  structural tier
     c = c0 + theta * G, with n the circuit width and G the baseline transpiled size.
  2. ORDER by diversity first: greedy coverage of (circuit_family, backend_id, effective oracle tier)
     combinations; among units of equal coverage status the cheaper (estimated) unit first; severity
     (decomposed._severity: circuit criticality x connectivity pressure) only breaks remaining ties.
  3. BUDGET with the same estimate: take units in that order while the cumulative ESTIMATED cost fits.

If the current machine is not of the same speed class as the previous sessions (baseline-transpilation speed
ratio outside [0.8, 1.25], see ``speed_factor``), previous-session oracle costs are rescaled by that ratio.

Design choices and the development evidence behind them (results/phase_c_dev.json, exploratory):

  * Oracle cost must be estimated, not assumed. In both labelled cohorts the exact unitary checks of the eight
    12-qubit line units take 25-285 s each and are ~95% of the real suite cost, while the selectors' constant
    oracle prices are <= 0.2 s (cost_model.ORACLE_COST_EST). With constant prices, cost-ordered and
    diversity-first selections overran the frozen pr budget 51-219x; with near-perfect cost knowledge the
    overrun disappeared and the composite's AUC gap to diversity-only shrank from 0.112 to 0.013.
  * Previous-session measurements are the primary estimator because per-unit oracle costs transfer across
    sessions (scale-up session / primary session ratio 0.88-1.03 on the eight expensive units, measured on
    different cloud machines); they need no model and no current-event information.
  * The analytic fallback exists only for units without history (new units); it uses pre-execution features
    only (oracle tier from the unit's width and coupling-map size, width n, baseline transpiled size G), and
    its form follows the cost of building a dense 2^n x 2^n operator gate by gate (G * 4^n).
  * Diversity first, cost second, severity last: under accurate costs, diversity_only, cheapest_first and
    decomposed all reached the detection ceiling on the development cohorts, while the composite's residual
    deficit was mostly its multiplicative severity term (removing it recovered most of the gap). Severity is
    therefore kept only as a tie-break, exactly as in ``decomposed``.
  * The oracle tier is part of the coverage key because only the exact tier can expose a semantics-breaking
    fault (the structural tier cannot assert equivalence) and the cheapest exact units cost milliseconds, so
    covering each (family, backend, tier) early is cheap. This choice is NOT supported by the development
    cohorts (they contain no semantic fault class); it is a design rationale, and its effect on development
    data is reported (COAST with and without the tier key).

Uses only pre-execution information: the static manifest, the baseline profile and costs measured in EARLIER
sessions. It never reads the current event's labels. ``baselines.py``, ``proposed.py``, ``decomposed.py``,
``cost_model.py`` and the existing registries are not modified; COAST is wired in through
``registry_phase_c.SELECTORS_PHASE_C``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from cart.selectors.context import SelectionContext
from cart.selectors.decomposed import _severity

_REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_COST_MODEL = _REPO_ROOT / "configs" / "phase_c_cost_model.json"
UNITARY_MAX_QUBITS = 12      # cart.oracles.semantic.UNITARY_MAX_QUBITS (exact tier ceiling)


# ------------------------------------------------------------------------------------------- oracle tier
def coupling_map_size(backend_id: str, n: int) -> int:
    from cart.manifest.backends import coupling_map_for
    return int(coupling_map_for(backend_id, n).size())


def effective_oracle_tier(unit) -> str:
    """Pre-execution prediction of the oracle tier the labeling engine will apply (cart.oracles.semantic):
    'exact' iff the unit is unitary-pure ('unitary' manifest tier), n <= 12 and the coupling map has exactly
    n qubits (otherwise the transpiled circuit carries ancillas and the engine falls back to 'structural')."""
    if unit.oracle_type == "unitary" and unit.n_qubits <= UNITARY_MAX_QUBITS \
            and coupling_map_size(unit.backend_id, unit.n_qubits) == unit.n_qubits:
        return "exact"
    return "structural"


# ------------------------------------------------------------------------------------------- analytic model
@dataclass(frozen=True)
class AnalyticOracleModel:
    """exact: c = c0_exact + theta_exact * G * 4^n ;  structural: c = c0_struct + theta_struct * G."""
    c0_exact: float
    theta_exact: float
    c0_struct: float
    theta_struct: float

    @staticmethod
    def feature(tier: str, n: int, g: float) -> float:
        return float(g) * (4.0 ** n) if tier == "exact" else float(g)

    def predict(self, tier: str, n: int, g: float) -> float:
        x = self.feature(tier, n, g)
        if tier == "exact":
            return self.c0_exact + self.theta_exact * x
        return self.c0_struct + self.theta_struct * x

    def to_dict(self) -> dict[str, float]:
        return dict(c0_exact=self.c0_exact, theta_exact=self.theta_exact,
                    c0_struct=self.c0_struct, theta_struct=self.theta_struct)


def _fit_tier(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Pre-declared fitting rule: c0 = smallest observed cost in the tier (the fixed per-check overhead);
    theta = geometric mean of (y - c0) / x over the units whose cost exceeds 2 * c0 (the units where the
    size-dependent term dominates). Closed form, no tuning parameter."""
    c0 = min(ys)
    ratios = [(y - c0) / x for x, y in zip(xs, ys) if y > 2 * c0 and x > 0]
    if not ratios:
        return c0, 0.0
    theta = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
    return c0, theta


def fit_analytic(rows: Iterable[dict[str, Any]]) -> AnalyticOracleModel:
    """rows: dicts with tier, n, g (baseline transpiled size) and oracle_s (unit-level mean oracle cost)."""
    ex = [r for r in rows if r["tier"] == "exact"]
    st = [r for r in rows if r["tier"] != "exact"]
    c0e, te = _fit_tier([AnalyticOracleModel.feature("exact", r["n"], r["g"]) for r in ex], [r["oracle_s"] for r in ex])
    c0s, ts = _fit_tier([AnalyticOracleModel.feature("structural", r["n"], r["g"]) for r in st], [r["oracle_s"] for r in st])
    return AnalyticOracleModel(c0e, te, c0s, ts)


# ------------------------------------------------------------------------------------------- estimator
@dataclass
class OracleCostEstimator:
    """Previous-session oracle cost per unit, with the analytic model as fallback for unseen units."""
    prev_oracle_s: dict[str, float]
    analytic: AnalyticOracleModel
    out_size: dict[str, float] = field(default_factory=dict)   # baseline transpiled size G per unit
    use_previous: bool = True                                 # False -> analytic for every unit
    speed_factor: float = 1.0                                 # machine-speed ratio (current / previous sessions)

    def source(self, test_id: str) -> str:
        return "previous_session" if (self.use_previous and test_id in self.prev_oracle_s) else "analytic"

    def oracle_cost(self, unit) -> float:
        if self.use_previous and unit.test_id in self.prev_oracle_s:
            return float(self.prev_oracle_s[unit.test_id]) * self.speed_factor
        g = self.out_size.get(unit.test_id)
        if g is None:            # no baseline profile either: crude, documented size proxy
            g = 10.0 * unit.n_qubits
        return float(self.analytic.predict(effective_oracle_tier(unit), unit.n_qubits, g)) * self.speed_factor

    def to_dict(self) -> dict[str, Any]:
        return {"prev_oracle_s": self.prev_oracle_s, "analytic": self.analytic.to_dict(),
                "out_size": self.out_size, "use_previous": self.use_previous, "speed_factor": self.speed_factor}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OracleCostEstimator":
        return cls(prev_oracle_s={k: float(v) for k, v in d["prev_oracle_s"].items()},
                   analytic=AnalyticOracleModel(**d["analytic"]),
                   out_size={k: float(v) for k, v in d.get("out_size", {}).items()},
                   use_previous=bool(d.get("use_previous", True)), speed_factor=float(d.get("speed_factor", 1.0)))


def session_unit_table(root: str | Path) -> dict[str, dict[str, float]]:
    """Per-unit means over all labelled events of ONE earlier session (data root): oracle_cost_s, cpu_time_s,
    total_cost_s, and the baseline transpiled size out_size (profiles.json)."""
    root = Path(root)
    labels = json.loads((root / "derived" / "labels.json").read_text())["labels"]
    acc: dict[str, dict[str, list]] = {}
    for r in labels:
        a = acc.setdefault(r["test_id"], {"oracle_cost_s": [], "cpu_time_s": [], "total_cost_s": []})
        for k in a:
            a[k].append(float(r[k]))
    out = {t: {k: sum(v) / len(v) for k, v in a.items()} for t, a in acc.items()}
    prof = root / "profile_baseline" / "profiles.json"
    if prof.exists():
        sizes: dict[str, list] = {}
        for p in json.loads(prof.read_text())["profiles"]:
            if p.get("out_size") is not None:
                sizes.setdefault(p["test_id"], []).append(float(p["out_size"]))
        for t, v in sizes.items():
            if t in out:
                out[t]["out_size"] = median(v)
    return out


def speed_factor(current_cpu_s: dict[str, float], previous_cpu_s: dict[str, float], *, min_prev_s: float = 0.05,
                 band: tuple[float, float] = (0.8, 1.25)) -> tuple[float, float]:
    """Machine-speed ratio between the current session and the previous sessions, from BASELINE transpilation CPU
    cost only (pre-execution): k = median over units with previous cost >= min_prev_s of current / previous.
    Returns (k_raw, k_applied) where k_applied = 1.0 when k_raw lies inside `band` (same machine class) and k_raw
    otherwise. Rationale: oracle and transpilation are both single-threaded CPU work; in the development check the
    sandbox / Kaggle ratio was 0.47 for transpilation and 0.53 for a 12-qubit exact check."""
    r = sorted(current_cpu_s[t] / previous_cpu_s[t] for t in current_cpu_s
               if t in previous_cpu_s and previous_cpu_s[t] >= min_prev_s and current_cpu_s[t] > 0)
    if not r:
        return 1.0, 1.0
    k = float(median(r))
    return k, (1.0 if band[0] <= k <= band[1] else k)


def estimator_from_sessions(roots: Iterable[str | Path], units: dict) -> tuple[OracleCostEstimator, dict]:
    """Build the COAST estimator from one or more EARLIER sessions. Per unit, the oracle estimate is the
    unweighted mean of the per-session means; the analytic model is fitted on the same per-unit means.
    `units` maps test_id -> TestUnit (for tier and width). Returns (estimator, pooled per-unit table)."""
    tables = [session_unit_table(r) for r in roots]
    pooled: dict[str, dict[str, float]] = {}
    for t in sorted(set().union(*[set(tb) for tb in tables])):   # sorted: summation order independent of PYTHONHASHSEED
        rows = [tb[t] for tb in tables if t in tb]
        pooled[t] = {k: sum(r[k] for r in rows if k in r) / max(1, sum(1 for r in rows if k in r))
                     for k in ("oracle_cost_s", "cpu_time_s", "total_cost_s", "out_size")
                     if any(k in r for r in rows)}
    fit_rows = [dict(tier=effective_oracle_tier(units[t]), n=units[t].n_qubits, g=pooled[t]["out_size"],
                     oracle_s=pooled[t]["oracle_cost_s"]) for t in sorted(pooled) if t in units and "out_size" in pooled[t]]
    model = fit_analytic(fit_rows)
    est = OracleCostEstimator(prev_oracle_s={t: v["oracle_cost_s"] for t, v in pooled.items()}, analytic=model,
                              out_size={t: v["out_size"] for t, v in pooled.items() if "out_size" in v})
    return est, pooled


_DEFAULT: OracleCostEstimator | None = None


def default_estimator() -> OracleCostEstimator:
    """The FROZEN Phase C estimator (configs/phase_c_cost_model.json, written before any Phase C label)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = OracleCostEstimator.from_dict(json.loads(FROZEN_COST_MODEL.read_text())["estimator"])
    return _DEFAULT


# ------------------------------------------------------------------------------------------- selector
def coast_costs(ctx: SelectionContext, event_id: str, estimator: OracleCostEstimator) -> dict[str, float]:
    return {t: float(ctx.baseline_cost(event_id, t)) + estimator.oracle_cost(ctx.test_meta(t))
            for t in ctx.candidate_test_ids()}


def coast_selector(ctx: SelectionContext, event_id: str, budget_s: float, *,
                   estimator: OracleCostEstimator | None = None, tier_key: bool = True,
                   use_severity: bool = True, **_) -> list[str]:
    """Ordered selection within `budget_s` (seconds, as estimated). budget_s = inf gives the full ranking."""
    est = estimator if estimator is not None else default_estimator()
    ids = ctx.candidate_test_ids()
    cost = coast_costs(ctx, event_id, est)

    def key(t: str):
        m = ctx.test_meta(t)
        return (m.circuit_family, m.backend_id, effective_oracle_tier(m)) if tier_key else (m.circuit_family, m.backend_id)

    combo = {t: key(t) for t in ids}
    sev = {t: (_severity(ctx, t) if use_severity else 0.0) for t in ids}
    seen: set = set()
    chosen: list[str] = []
    spent = 0.0
    remaining = list(ids)
    while remaining:
        remaining.sort(key=lambda t: (combo[t] in seen, cost[t], -sev[t], t))
        picked = next((t for t in remaining if spent + cost[t] <= budget_s), None)
        if picked is None:
            break
        chosen.append(picked)
        spent += cost[picked]
        seen.add(combo[picked])
        remaining.remove(picked)
    return chosen
