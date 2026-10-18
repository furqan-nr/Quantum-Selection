"""Frozen Phase E analysis (PREREGISTRATION_PHASE_E.md, Sections 5-8). Deterministic; standard library only.

    python phase_e/analysis/phase_e_analysis.py --lock E1 [E2 ...]   # budget locks (after P runs + B collect, before B runs)
    python phase_e/analysis/phase_e_analysis.py                      # the one confirmatory run -> results/phase_e_confirmatory.json

Inputs (phase_e/data/assembled/, written by `run_phase_e.py assemble`):
  run_w{V}_t{V}_pass{k}.json   per-test records of a timing pass (P: pass 1; B: passes 1 and 2)
  collect_{B}.json             collect-only list of B's slice (the pair suite, known before any B timing pass)
Budget locks: phase_e/data/budget_lock/{E}.json (written by --lock; the final run asserts equality).

Definitions (all frozen; the estimator specifications are read from phase_e/config/phase_e_config.json):
  suite S_e      B's collect-only list (normalized ids, collection order). No backported or added tests.
  est(t)         P pass-1 duration of the same normalized id ('seen'); an unseen test is priced by the estimator's
                 unseen rule: 'in_file' if its logical file has >= min_seen seen tests, else 'new_file'; times the
                 speed factor k if k = cal(B collect call) / median cal(P run calls) is outside the speed band
  r(t)           mean B duration over the timing passes with a record (timeouts = per-test timeout); missing -> est
                 (counted as n_imputed_real, a deviation)
  budgets        b_f = f * sum_{t in S_e} est(t), f in {0.05, 0.25} (0.5 exploratory), per estimator
  plans          cheapest_first: ascending est, greedy with skip within b_f; coast_d: COAST with key = logical test
                 file (identical to Phase D); EVERY planned test is charged its real cost (nothing excluded)
  P1'            for the PRIMARY estimator, policies cheapest_first and coast_d, f in {0.05, 0.25}: EVERY pair's
                 real spend / budget <= 1.25 (all four criteria; the mean <= 1.25 follows)
  P2'            for the PRIMARY estimator: e_p = sum est / sum r - 1 over S_e; median |e_p| <= 0.15 AND at least
                 80% of the analysable pairs have |e_p| <= 0.25
  roles          confirmatory: P1', P2' (primary estimator only). Registered secondary (same rules, labelled
                 secondary, no confirmatory claim): the secondary estimator. Continuity checks (no claim): Phase D's
                 P1 thresholds (mean <= 1.25, single pair <= 2.0) and Phase D's strict P2 (every pair within +-25%).
                 Comparator: Phase D's registered estimator (exploratory). Pairs failing the environment rule (decided
                 at lock time from P's run and B's collect list) are excluded; >= min_analysable_pairs are required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ io / helpers
def _load(p: Path):
    return json.loads(Path(p).read_text())


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fsum_sorted(xs) -> float:
    return math.fsum(sorted(xs))


def r6(x):
    return None if x is None else round(float(x), 6)


def file_of(tid: str) -> str:
    return tid.split("::", 1)[0]


def quantile(xs, q: float) -> float:
    """Linear interpolation between order statistics (Hyndman-Fan type 7, numpy's default)."""
    v = sorted(xs)
    if not v:
        raise ValueError("quantile of an empty list")
    h = (len(v) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (h - lo)


def stat(xs, spec: dict) -> float:
    s = spec["stat"]
    if s == "median":
        return statistics.median(sorted(xs))
    if s == "mean":
        return fsum_sorted(xs) / len(xs)
    if s == "quantile":
        return quantile(xs, float(spec["q"]))
    if s == "max":
        return max(xs)
    raise ValueError(f"unknown stat {s}")


# ------------------------------------------------------------------------------------------------ estimator
def estimator(suite: list[str], pdur: dict[str, float], spec: dict, k: float = 1.0):
    """est per suite test and its source ('seen', 'in_file', 'new_file').

    spec (frozen in the config):
      min_seen   a file with >= min_seen seen tests prices its unseen tests by 'in_file', otherwise 'new_file'
      in_file    {"stat": median|mean|quantile[, "q"]} over the P durations of the file's seen tests
                 optional "shrink_kappa": the file statistic m_f is shrunk towards the same statistic over all P
                 durations: (n_f * m_f + kappa * m_global) / (n_f + kappa)
                 optional "floor_global": price = max(file statistic, the same statistic over all P durations)
      new_file   {"stat": ..., "over": "tests" (all P durations) | "file_means" (one mean per P file)}
      scale      multiplier applied to every UNSEEN price (default 1)
    Seen tests are always priced at their own P duration."""
    by_file: dict[str, list[float]] = {}
    for tid, d in pdur.items():
        by_file.setdefault(file_of(tid), []).append(d)
    allv = list(pdur.values())
    m = int(spec["min_seen"])
    ins, nfs = spec["in_file"], spec["new_file"]
    scale = float(spec.get("scale", 1.0))
    if nfs.get("over", "tests") == "file_means":
        g_new = stat([fsum_sorted(v) / len(v) for v in by_file.values()], nfs) if by_file else 0.0
    else:
        g_new = stat(allv, nfs) if allv else 0.0
    g_in = stat(allv, ins) if allv else 0.0
    cache: dict[str, float] = {}
    est, src = {}, {}
    for t in suite:
        if t in pdur:
            est[t], src[t] = pdur[t], "seen"
            continue
        f = file_of(t)
        vals = by_file.get(f, [])
        if len(vals) >= m:
            if f not in cache:
                mf = stat(vals, ins)
                if ins.get("shrink_kappa") is not None:
                    kap = float(ins["shrink_kappa"])
                    mf = (len(vals) * mf + kap * g_in) / (len(vals) + kap)
                if ins.get("floor_global"):
                    mf = max(mf, g_in)
                cache[f] = mf
            est[t], src[t] = cache[f] * scale, "in_file"
        else:
            est[t], src[t] = g_new * scale, "new_file"
    return {t: v * k for t, v in est.items()}, src


# ------------------------------------------------------------------------------------------------ plans
def order_cheapest(suite, cost):
    pos = {t: i for i, t in enumerate(suite)}
    return sorted(suite, key=lambda t: (cost[t], pos[t]))


def plan_greedy(order, cost, budget):
    chosen, spent = [], 0.0
    for t in order:
        if spent + cost[t] <= budget:
            chosen.append(t)
            spent += cost[t]
    return chosen


def coast_d(suite, cost, budget=math.inf):
    """COAST with coverage key = logical test file, ties by CI order (identical to phase_d_analysis.coast_d)."""
    pos = {t: i for i, t in enumerate(suite)}
    srt = sorted(suite, key=lambda t: (cost[t], pos[t]))
    seen, chosen, pool, spent = set(), [], [], 0.0
    for t in srt:
        f = file_of(t)
        if f in seen:
            pool.append(t)
        elif spent + cost[t] <= budget:
            chosen.append(t)
            spent += cost[t]
            seen.add(f)
    for t in pool:
        if spent + cost[t] <= budget:
            chosen.append(t)
            spent += cost[t]
    return chosen


def plans_for(suite, est, budget) -> dict[str, list[str]]:
    return {"cheapest_first": plan_greedy(order_cheapest(suite, est), est, budget), "coast_d": coast_d(suite, est, budget)}


# ------------------------------------------------------------------------------------------------ one pair, one estimator
def evaluate_estimator(suite, pdur, real, spec, k, fractions, per_pass=None) -> dict:
    """Budgets, plans, spend ratios (every planned test charged its real cost), suite-cost error, and the split of
    the spend into seen and unseen tests. Pure function: used identically on Phase D development data and on the
    Phase E study data."""
    est, src = estimator(suite, pdur, spec, k)
    tot_est, tot_real = fsum_sorted(est.values()), fsum_sorted(real[t] for t in suite)
    out = {"total_est_s": r6(tot_est), "total_real_s": r6(tot_real),
           "suite_cost_rel_error": r6(tot_est / tot_real - 1.0) if tot_real > 0 else None,
           "source_counts": {s: sum(1 for t in suite if src[t] == s) for s in ("seen", "in_file", "new_file")},
           "unseen_est_share": r6(fsum_sorted(est[t] for t in suite if src[t] != "seen") / tot_est) if tot_est else None,
           "unseen_real_share": r6(fsum_sorted(real[t] for t in suite if src[t] != "seen") / tot_real) if tot_real else None,
           "unseen_real_s": r6(fsum_sorted(real[t] for t in suite if src[t] != "seen")),
           "new_file_real_s": r6(fsum_sorted(real[t] for t in suite if src[t] == "new_file")),
           "budgets_s": {}, "lane_cost_ratio": {}, "tiers": {}}
    for f in fractions:
        b = f * tot_est
        out["budgets_s"][str(f)] = r6(b)
        # exploratory: an always-run lane for every unseen test would cost this multiple of the budget
        out["lane_cost_ratio"][str(f)] = r6(fsum_sorted(real[t] for t in suite if src[t] != "seen") / b) if b > 0 else None
        tier = {}
        for name, plan in plans_for(suite, est, b).items():
            seen = [t for t in plan if src[t] == "seen"]
            uns = [t for t in plan if src[t] != "seen"]
            row = {"selected": len(plan), "selected_unseen": len(uns),
                   "selected_in_file": sum(1 for t in uns if src[t] == "in_file"),
                   "selected_new_file": sum(1 for t in uns if src[t] == "new_file"),
                   "spend_ratio": r6(fsum_sorted(real[t] for t in plan) / b) if b > 0 else None,
                   "est_spend_ratio": r6(fsum_sorted(est[t] for t in plan) / b) if b > 0 else None,
                   "spend_ratio_seen_part": r6(fsum_sorted(real[t] for t in seen) / b) if b > 0 else None,
                   "spend_ratio_unseen_part": r6(fsum_sorted(real[t] for t in uns) / b) if b > 0 else None,
                   "spend_vs_real_fraction_budget": r6(fsum_sorted(real[t] for t in plan) / (f * tot_real)) if tot_real > 0 else None}
            if per_pass:
                row["per_pass_spend_ratio"] = [r6(fsum_sorted(rp[t] for t in plan) / b) if b > 0 else None for rp in per_pass]
            tier[name] = row
        out["tiers"][str(f)] = tier
    return out


# ------------------------------------------------------------------------------------------------ decision rules
def decide_p1(rows: list[dict], rule: dict) -> dict:
    crit = {}
    for pol in rule["policies"]:
        for f in rule["fractions"]:
            rs = [r["tiers"][str(f)][pol]["spend_ratio"] for r in rows]
            m, mx = fsum_sorted(rs) / len(rs), max(rs)
            crit[f"{pol}@{f}"] = {"mean": r6(m), "max": r6(mx), "per_pair": rs,
                                  "holds": m <= rule["mean_spend_ratio_max"] and mx <= rule["single_pair_spend_ratio_max"]}
    return {"criteria": crit, "supported": all(v["holds"] for v in crit.values())}


def decide_p2(errs: list[float], rule: dict) -> dict:
    a = [abs(e) for e in errs]
    med = statistics.median(sorted(a))
    share = sum(1 for x in a if x <= rule["abs_rel_error_band"]) / len(a)
    return {"median_abs_rel_error": r6(med), "share_within_band": r6(share), "n_pairs": len(a),
            "n_within_band": sum(1 for x in a if x <= rule["abs_rel_error_band"]),
            "supported": med <= rule["median_abs_rel_error_max"] and share >= rule["min_share_within_band"] - 1e-12,
            "strict_every_pair_within_band": all(x <= rule["abs_rel_error_band"] for x in a)}


def p1_risk(p1: dict, rule: dict) -> float:
    """max over the P1 criteria of max(mean / mean threshold, max / single-pair threshold); < 1 iff P1 holds."""
    return max(max(v["mean"] / rule["mean_spend_ratio_max"], v["max"] / rule["single_pair_spend_ratio_max"])
               for v in p1["criteria"].values())


# ------------------------------------------------------------------------------------------------ study data
class Pair:
    def __init__(self, ev: dict, cfg: dict, data: Path):
        self.ev, self.cfg, self.data = ev, cfg, data
        self.eid, self.P, self.B = ev["event_id"], ev["P"], ev["B"]
        self.T = float(cfg["runner"]["per_test_timeout_s"])

    def p_run(self) -> Path:
        return self.data / f"run_w{self.P}_t{self.P}_pass1.json"

    def b_runs(self) -> list[Path]:
        n = int(self.cfg["runner"]["timing_passes_B"])
        return [self.data / f"run_w{self.B}_t{self.B}_pass{k}.json" for k in range(1, n + 1)]

    def b_collect(self) -> Path:
        return self.data / f"collect_{self.B}.json"


def suite_from_collect(collected: list[str]) -> list[str]:
    return list(dict.fromkeys(collected))


def p_durations(prun: dict, T: float) -> dict[str, float]:
    return {tid: (T if rec["outcome"] == "timeout" else float(rec["duration"])) for tid, rec in prun["tests"].items()}


def calibration(envs: list[dict]):
    xs = [x["calibration_median_s"] for x in envs if isinstance(x.get("calibration_median_s"), (int, float))]
    return statistics.median(xs) if xs else None


def speed_factor(prun: dict, bcollect: dict, band) -> dict:
    cp = calibration(prun.get("env", []))
    cb = bcollect.get("meta", {}).get("calibration_median_s")
    if not cp or not isinstance(cb, (int, float)):
        return {"k_measured": None, "k_applied": 1.0, "note": "calibration missing; k = 1"}
    km = cb / cp
    return {"k_measured": km, "k_applied": km if (km < band[0] or km > band[1]) else 1.0}


def estimator_specs(cfg: dict) -> dict[str, dict]:
    E = cfg["estimators"]
    return {"primary": E["primary"]["spec"], "secondary": E["secondary"]["spec"],
            "phase_d_registered": E["comparator_phase_d_registered"]["spec"]}


def fractions(cfg: dict) -> list[float]:
    return list(cfg["budgets"]["fractions_primary"]) + list(cfg["budgets"]["fractions_exploratory"])


def environment_check(prun: dict, bcol: dict, cfg: dict) -> dict:
    """Registered exclusion rule (decided at lock time, from P's run and B's collect list only, never from B
    durations): a pair is excluded if more than max_share_files_without_tests of the slice files have no test in
    B's collect list, or no test record in P's run (collection or import failure of the environment)."""
    lim = float(cfg["confirmatory"]["environment_exclusion"]["max_share_files_without_tests"])
    bfiles = list(bcol.get("meta", {}).get("files", []))
    bwith = {file_of(t) for t in bcol["collected"]}
    pfiles = list(prun.get("files", {}))
    pwith = {file_of(t) for t in prun["tests"]}
    b_share = (sum(1 for f in bfiles if f not in bwith) / len(bfiles)) if bfiles else 1.0
    p_share = (sum(1 for f in pfiles if f not in pwith) / len(pfiles)) if pfiles else 1.0
    return {"b_slice_files": len(bfiles), "b_files_without_tests": sorted(f for f in bfiles if f not in bwith),
            "p_slice_files": len(pfiles), "p_files_without_tests": sorted(f for f in pfiles if f not in pwith),
            "b_share": r6(b_share), "p_share": r6(p_share), "excluded": b_share > lim or p_share > lim}


def lock_record(e: Pair, cfg: dict) -> dict:
    prun, bcol = _load(e.p_run()), _load(e.b_collect())
    suite = suite_from_collect(bcol["collected"])
    pdur = p_durations(prun, e.T)
    sf = speed_factor(prun, bcol, cfg["estimator_common"]["speed_band"])
    env = environment_check(prun, bcol, cfg)
    out = {"event_id": e.eid, "P": e.P, "B": e.B, "p_run_sha256": _sha(e.p_run()), "b_collect_sha256": _sha(e.b_collect()),
           "p_run_complete": bool(prun.get("complete")), "suite_size": len(suite), "speed": sf,
           "environment_check": env, "estimators": {}}
    for name, spec in estimator_specs(cfg).items():
        est, src = estimator(suite, pdur, spec, sf["k_applied"])
        tot = fsum_sorted(est.values())
        out["estimators"][name] = {"total_est_s": r6(tot), "budgets_s": {str(f): r6(f * tot) for f in fractions(cfg)},
                                   "source_counts": {s: sum(1 for t in suite if src[t] == s) for s in ("seen", "in_file", "new_file")}}
    return out


def real_costs(e: Pair, suite: list[str], est: dict):
    passes = []
    for p in e.b_runs():
        if not p.exists():
            continue
        m = {}
        for tid, rec in _load(p)["tests"].items():
            m[tid] = (rec["outcome"], e.T if rec["outcome"] == "timeout" else float(rec["duration"]))
        passes.append(m)
    real, outs, imputed = {}, {}, []
    for t in suite:
        ds = [pm[t][1] for pm in passes if t in pm]
        outs[t] = [pm[t][0] for pm in passes if t in pm]
        if ds:
            real[t] = fsum_sorted(ds) / len(ds)
        else:
            real[t] = est[t]
            imputed.append(t)
    per_pass = [{t: (pm[t][1] if t in pm else real[t]) for t in suite} for pm in passes]
    return real, outs, imputed, per_pass, len(passes)


def analyse_pair(e: Pair, cfg: dict) -> dict:
    prun, bcol = _load(e.p_run()), _load(e.b_collect())
    suite = suite_from_collect(bcol["collected"])
    pdur = p_durations(prun, e.T)
    sf = speed_factor(prun, bcol, cfg["estimator_common"]["speed_band"])
    specs = estimator_specs(cfg)
    est_primary, _ = estimator(suite, pdur, specs["primary"], sf["k_applied"])
    real, outs, imputed, per_pass, n_passes = real_costs(e, suite, est_primary)
    fr = fractions(cfg)
    res = {"event_id": e.eid, "P": e.P, "B": e.B, "kind": e.ev.get("kind"), "suite_size": len(suite),
           "n_b_passes": n_passes, "speed": sf, "n_imputed_real": len(imputed),
           "outcome_counts_B_pass1": {}, "estimators": {}}
    if per_pass:
        oc: dict[str, int] = {}
        for t in suite:
            if outs[t]:
                oc[outs[t][0]] = oc.get(outs[t][0], 0) + 1
        res["outcome_counts_B_pass1"] = dict(sorted(oc.items()))
    for name, spec in specs.items():
        res["estimators"][name] = evaluate_estimator(suite, pdur, real, spec, sf["k_applied"], fr, per_pass)
    # exploratory: per-test accuracy of seen tests, B pass-to-pass noise, files new in B
    seen = [t for t in suite if t in pdur]
    big = [t for t in seen if real[t] >= 0.01]
    res["exploratory"] = {
        "per_test_median_ape_seen_ge_10ms": r6(statistics.median(abs(pdur[t] - real[t]) / real[t] for t in big)) if big else None,
        "seen_sum_rel_error": r6(fsum_sorted(pdur[t] for t in seen) / fsum_sorted(real[t] for t in seen) - 1.0) if seen else None,
        "files_new_in_B": sorted({file_of(t) for t in suite} - {file_of(t) for t in pdur}),
        "files_dropped_from_P": sorted({file_of(t) for t in pdur} - {file_of(t) for t in suite}),
        "per_pass_suite_real_s": [r6(fsum_sorted(rp.values())) for rp in per_pass],
    }
    res["_lock"] = lock_record(e, cfg)
    res["environment_check"] = res["_lock"]["environment_check"]
    return res


def decide(results: list[dict], cfg: dict) -> dict:
    C = cfg["confirmatory"]
    out = {"roles": {"confirmatory": ["P1prime", "P2prime"], "estimator": "primary",
                     "registered_secondary": "secondary (same rules; no confirmatory claim)",
                     "continuity_checks": "P1 with Phase D thresholds (mean 1.25, max 2.0); P2 strict (every pair within +-25%)",
                     "comparator_exploratory": "phase_d_registered"}}
    for name in ("primary", "secondary", "phase_d_registered"):
        rows = [r["estimators"][name] for r in results]
        p1 = decide_p1(rows, C["P1prime"])
        p2 = decide_p2([r["suite_cost_rel_error"] for r in rows], C["P2prime"])
        cont = decide_p1(rows, {**C["P1prime"], **C["continuity_checks"]["P1_phase_d_thresholds"]})
        out[name] = {"P1prime": p1, "P1prime_risk": r6(p1_risk(p1, C["P1prime"])), "P2prime": p2,
                     "P1_continuity_phase_d_thresholds": cont["supported"],
                     "P2_strict_continuity": p2["strict_every_pair_within_band"],
                     "rel_error_per_pair": {r["event_id"]: r["estimators"][name]["suite_cost_rel_error"] for r in results}}
    out["P1prime_supported"] = out["primary"]["P1prime"]["supported"]
    out["P2prime_supported"] = out["primary"]["P2prime"]["supported"]
    return out


def leakage_checks(ledger: dict, cfg: dict) -> list[dict]:
    vs = cfg["versions"]
    used = cfg["releases_used_in_phase_d_any_role"]
    out, seen = [], {}
    for ev in ledger["events"]:
        P, B = ev["P"], ev["B"]
        for v in (P, B):
            seen[v] = seen.get(v, 0) + 1
        out.append({"event_id": ev["event_id"], "P_ne_B": P != B,
                    "P_uploaded_before_B": vs[P]["upload_time_utc"] < vs[B]["upload_time_utc"],
                    "fresh": P not in used and B not in used})
    return out + [{"disjoint_pairs": all(c == 1 for c in seen.values())}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(REPO / "phase_e/config/phase_e_config.json"))
    ap.add_argument("--ledger", default=str(REPO / "phase_e/events/phase_e_pairs.json"))
    ap.add_argument("--data", default=str(REPO / "phase_e/data/assembled"))
    ap.add_argument("--locks", default=str(REPO / "phase_e/data/budget_lock"))
    ap.add_argument("--out", default=str(REPO / "results/phase_e_confirmatory.json"))
    ap.add_argument("--lock", nargs="*", help="write budget locks for these pairs (before any B timing pass)")
    args = ap.parse_args()
    cfg, ledger, data = _load(Path(args.config)), _load(Path(args.ledger)), Path(args.data)
    pairs = [Pair(ev, cfg, data) for ev in ledger["events"]]
    locks = Path(args.locks)
    if args.lock is not None:
        unknown = set(args.lock) - {e.eid for e in pairs}
        if unknown:
            raise SystemExit(f"unknown pairs: {sorted(unknown)}")
        locks.mkdir(parents=True, exist_ok=True)
        for e in pairs:
            if e.eid not in args.lock:
                continue
            raw = data.parent / "runs" / f"w{e.B}_t{e.B}"
            if any(p.exists() for p in e.b_runs()) or (raw.exists() and any(raw.rglob("*"))):
                raise SystemExit(f"{e.eid}: B timing data of {e.B} already exist (assembled or raw); "
                                 "the lock must precede every B timing pass")
            if not e.p_run().exists() or not e.b_collect().exists():
                raise SystemExit(f"{e.eid}: P run or B collect list missing")
            rec = lock_record(e, cfg)
            if not rec["p_run_complete"]:
                raise SystemExit(f"{e.eid}: P run of {e.P} is incomplete")
            lk = locks / f"{e.eid}.json"
            if lk.exists():
                old = _load(lk)
                if {k: old.get(k) for k in rec} != rec:
                    raise SystemExit(f"{e.eid}: a different budget lock already exists; locks are never rewritten")
                print(json.dumps({"unchanged": str(lk)}))
                continue
            rec["locked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            rec["analysis_sha256"] = _sha(Path(__file__))
            rec["config_sha256"] = _sha(Path(args.config))
            lk.write_text(json.dumps(rec, indent=1, sort_keys=True))
            print(json.dumps({"locked": e.eid, "primary_budgets_s": rec["estimators"]["primary"]["budgets_s"]}))
        return
    results, excluded, deviations = [], [], []
    for e in pairs:
        missing = [p.name for p in [e.p_run(), e.b_collect()] + e.b_runs() if not p.exists()]
        if not e.p_run().exists() or not e.b_collect().exists() or not any(p.exists() for p in e.b_runs()):
            excluded.append({"event_id": e.eid, "missing": missing})
            deviations.append(f"{e.eid}: excluded (missing {', '.join(missing)})")
            continue
        if missing:
            deviations.append(f"{e.eid}: analysed with missing {', '.join(missing)}")
        r = analyse_pair(e, cfg)
        lock = r.pop("_lock")
        if lock["environment_check"]["excluded"]:
            excluded.append({"event_id": e.eid, "environment_check": lock["environment_check"]})
            deviations.append(f"{e.eid}: excluded by the registered environment rule (files without tests: "
                              f"B {lock['environment_check']['b_share']}, P {lock['environment_check']['p_share']})")
            continue
        lk = locks / f"{e.eid}.json"
        if lk.exists():
            frozen = _load(lk)
            r["budget_lock_matches"] = all(frozen.get(k) == lock[k] for k in ("p_run_sha256", "b_collect_sha256", "estimators",
                                                                              "speed", "environment_check"))
            if not r["budget_lock_matches"]:
                deviations.append(f"{e.eid}: budget lock mismatch")
        else:
            r["budget_lock_matches"] = None
            deviations.append(f"{e.eid}: no budget lock")
        if r["n_imputed_real"]:
            deviations.append(f"{e.eid}: {r['n_imputed_real']} suite tests without a B record (charged est)")
        results.append(r)
    if not results:
        raise SystemExit("no analysable pair")
    min_pairs = int(cfg["confirmatory"]["min_analysable_pairs"])
    dec = decide(results, cfg)
    if len(results) < min_pairs:
        deviations.append(f"only {len(results)} analysable pairs (< {min_pairs}): P1' and P2' are reported but not decided")
        dec["P1prime_supported"] = dec["P2prime_supported"] = None
    out = {"schema": "phase_e_confirmatory/1", "pairs": results, "excluded_pairs": excluded, "decisions": dec,
           "leakage_checks": leakage_checks(ledger, cfg), "deviations": deviations,
           "inputs_sha256": {p.name: _sha(p) for p in sorted(data.glob("*.json"))},
           "config_sha256": _sha(Path(args.config)), "analysis_sha256": _sha(Path(__file__))}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({"wrote": args.out, "P1prime": dec["P1prime_supported"], "P2prime": dec["P2prime_supported"],
                      "deviations": deviations}))


if __name__ == "__main__":
    main()
