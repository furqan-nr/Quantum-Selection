"""Frozen Phase D analysis (PREREGISTRATION_PHASE_D.md, Sections 6-9). Deterministic; standard library only.

    python phase_d/analysis/phase_d_analysis.py --lock E1 [E2 ...]   # budget lock (after P runs + B collect, before B runs)
    python phase_d/analysis/phase_d_analysis.py                      # the one confirmatory run -> results/phase_d_confirmatory.json

Inputs (phase_d/data/assembled/, written by `run_phase_d.py assemble`):
  run_w{V}_t{V}_pass{k}.json   per-test records of a timing pass (P: pass 1; B: passes 1 and 2)
  collect_{B}.json             collect-only list of B's slice + backports (the event suite, known before any B run)
  fcheck_{E}.json              F-run of event E (backported tests + B's non-passing pre-existing tests on the F wheel)
Budget locks: phase_d/data/budget_lock/{E}.json (written by --lock; the final run asserts equality).

Definitions (all frozen):
  suite S_e      B collect list without backport files, plus the event's own backported tests under their logical ids
  est(t)         P pass-1 duration of the same normalized id (P's own slice files only); unseen tests: median of the
                 seen tests of the same logical file if >= 3, else the global median of P; times the speed factor k
                 if k = cal(B collect call) / median cal(P run calls) is outside [0.8, 1.25]
  r(t)           mean B duration over the timing passes with a record (timeouts = per-test timeout); missing -> est
  D_e            tests of S_e that did not pass (failed/error/timeout/crash) in every B pass with a record and passed on F
  budgets        b_f = f * sum_{t in S_e} est(t), f in {0.05, 0.25} (0.5 exploratory)
  default order  files in sorted path order, B's collection order; a backported test where pytest would collect it
                 had the method been added to B's class of the same name (sorted method names); new class: file end
  roles          confirmatory: P1 (real spend of the plan's pre-existing tests / budget), P2 (pre-existing suite
                 cost estimate); registered forecast checks: H1, H2, D1 (near-certain by construction, Section 9.2)
  policies       default (CI order), random (100 seeds), file_rr (round robin over files): cost-blind, time-boxed;
                 cheapest_first, coast_d (COAST with key = logical test file): planned with est (greedy with skip),
                 then executed under the same real time box; cheapest_oracle (real costs): exploratory reference
  APFDc          single-fault cost-cognizant APFD of the full order: 1 - (C_before + r_first / 2) / C_total; 0 if D_e empty
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import statistics
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NONPASS = ("failed", "error", "timeout", "crash")


# ------------------------------------------------------------------------------------------------ io
def _load(p: Path):
    return json.loads(p.read_text())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fsum_sorted(xs) -> float:
    return math.fsum(sorted(xs))


def r6(x: float) -> float:
    return round(float(x), 6)


# ------------------------------------------------------------------------------------------------ suite / estimator
class Event:
    def __init__(self, ev: dict, cfg: dict, data: Path):
        self.ev, self.cfg, self.data = ev, cfg, data
        self.eid, self.P, self.B, self.F = ev["event_id"], ev["P"], ev["B"], ev["F"]
        self.bdir = cfg["slice"]["backport_dir"]
        self.T = float(cfg["runner"]["per_test_timeout_s"])
        bf = ev.get("backport_file")
        self.bp_phys_file = f"{self.bdir}/{Path(bf).name}" if bf else None
        self.logical_file = ev.get("logical_file")

    def to_logical(self, tid: str) -> str | None:
        """Physical id -> logical id; None for tests of other events' backport files."""
        f = tid.split("::", 1)[0]
        if f.startswith(self.bdir + "/"):
            if self.bp_phys_file and f == self.bp_phys_file:
                return self.logical_file + "::" + tid.split("::", 1)[1]
            return None
        return tid

    # paths
    def p_run(self) -> Path:
        return self.data / f"run_w{self.P}_t{self.P}_pass1.json"

    def b_runs(self) -> list[Path]:
        n = int(self.cfg["runner"]["timing_passes_B"])
        return [self.data / f"run_w{self.B}_t{self.B}_pass{k}.json" for k in range(1, n + 1)]

    def b_collect(self) -> Path:
        return self.data / f"collect_{self.B}.json"

    def fcheck(self) -> Path:
        return self.data / f"fcheck_{self.eid}.json"


def file_of(tid: str) -> str:
    return tid.split("::", 1)[0]


def class_of(tid: str) -> str:
    parts = tid.split("::")
    return "::".join(parts[:-1])


def method_of(tid: str) -> str:
    return tid.split("::")[-1]


def build_suite(e: Event, collected: list[str]) -> tuple[list[str], dict[str, tuple], set[str]]:
    """Returns the suite in default (CI) order, the sort key per test, and the backport (logical) ids.

    Default (CI) order = pytest's order for `pytest test/python/compiler test/python/transpiler`: files in sorted path
    order, tests in B's collection order. Position rule for a backported test (registered, Section 3): where pytest
    would collect it had the method been added to B's own class of the same name in its logical file. pytest collects
    the methods of a unittest.TestCase class in sorted name order (unittest.TestLoader.getTestCaseNames), so the test
    goes right after the last B test of that class whose method name sorts before it (Python string order), or right
    before the class's first test if none does. A backported class that does not exist in B's file (D2's added
    test) goes at the end of its logical file. Key = (file, anchor index, side, method name, collection index)."""
    pre: dict[str, int] = {}
    bp_idx: dict[str, int] = {}
    for idx, tid in enumerate(collected):
        lid = e.to_logical(tid)
        if lid is None:
            continue
        if lid != tid:
            bp_idx.setdefault(lid, idx)
        elif lid not in pre:
            pre[lid] = idx
    by_class: dict[str, list[tuple[str, int]]] = {}
    for t, idx in pre.items():
        by_class.setdefault(class_of(t), []).append((method_of(t), idx))
    key: dict[str, tuple] = {t: (file_of(t), idx, 0, "", idx) for t, idx in pre.items()}
    for b, idx in bp_idx.items():
        if b in key:                                    # collision with a pre-existing id: reported, kept once
            continue
        members = by_class.get(class_of(b), [])
        name = method_of(b)
        smaller = [i for m, i in members if m < name]
        if smaller:
            key[b] = (file_of(b), max(smaller), 1, name, idx)
        elif members:
            key[b] = (file_of(b), min(i for _, i in members), -1, name, idx)
        else:
            key[b] = (file_of(b), math.inf, 1, name, idx)
    order = sorted(key, key=lambda t: key[t])
    return order, key, set(bp_idx)


def backport_collisions(e: Event, collected: list[str]) -> list[str]:
    """Backported logical ids that coincide with a pre-existing B id (expected: none; reported as a deviation)."""
    pre = {t for t in collected if e.to_logical(t) == t}
    return sorted({e.to_logical(t) for t in collected if e.to_logical(t) not in (None, t) and e.to_logical(t) in pre})


def alt_default_orders(suite: list[str], key: dict, bp: set) -> dict[str, list[str]]:
    """Exploratory default-order variants: backported tests at the end / start of their logical file, and the
    directory-argument order `pytest test/python/transpiler test/python/compiler` (transpiler files first)."""
    def k_end(t):
        return (key[t][0], 1 if t in bp else 0, key[t][4])

    def k_start(t):
        return (key[t][0], -1 if t in bp else 0, key[t][4])

    def k_tfirst(t):
        return (0 if key[t][0].startswith("test/python/transpiler/") else 1,) + tuple(key[t])
    return {"backport_at_file_end": sorted(suite, key=k_end), "backport_at_file_start": sorted(suite, key=k_start),
            "transpiler_dir_first": sorted(suite, key=k_tfirst)}


def p_durations(e: Event, prun: dict) -> dict[str, float]:
    out = {}
    for tid, rec in prun["tests"].items():
        if file_of(tid).startswith(e.bdir + "/"):
            continue                                    # P's own slice files only
        out[tid] = e.T if rec["outcome"] == "timeout" else float(rec["duration"])
    return out


def calibration(envs: list[dict]) -> float | None:
    xs = [x["calibration_median_s"] for x in envs if isinstance(x.get("calibration_median_s"), (int, float))]
    return statistics.median(xs) if xs else None


def estimator(suite: list[str], pdur: dict[str, float], min_seen: int, k: float, rule: str = "registered"):
    """est per suite test and its source ('seen', 'file_median', 'global_median'). Alternative rules (exploratory):
    'global_only' (global median for every unseen test), 'file_mean', 'zero'."""
    by_file: dict[str, list[float]] = {}
    for tid, d in pdur.items():
        by_file.setdefault(file_of(tid), []).append(d)
    gmed = statistics.median(sorted(pdur.values())) if pdur else 0.0
    est, src = {}, {}
    for t in suite:
        if t in pdur:
            est[t], src[t] = pdur[t], "seen"
            continue
        f = by_file.get(file_of(t), [])
        if rule == "zero":
            est[t], src[t] = 0.0, "zero"
        elif rule == "file_mean" and len(f) >= min_seen:
            est[t], src[t] = fsum_sorted(f) / len(f), "file_mean"
        elif rule == "registered" and len(f) >= min_seen:
            est[t], src[t] = statistics.median(sorted(f)), "file_median"
        else:
            est[t], src[t] = gmed, "global_median"
    return {t: v * k for t, v in est.items()}, src


def speed_factor(e: Event, prun: dict, bcollect: dict, band) -> dict:
    cp = calibration(prun.get("env", []))
    cb = bcollect.get("meta", {}).get("calibration_median_s")
    if not cp or not isinstance(cb, (int, float)):
        return {"k_measured": None, "k_applied": 1.0, "note": "calibration missing; k = 1"}
    km = cb / cp
    return {"k_measured": km, "k_applied": km if (km < band[0] or km > band[1]) else 1.0}


# ------------------------------------------------------------------------------------------------ policies
def order_default(suite):
    return list(suite)


def order_random(suite, seed):
    o = list(suite)
    random.Random(seed).shuffle(o)
    return o


def order_file_rr(suite):
    by_file: dict[str, list[str]] = {}
    for t in suite:
        by_file.setdefault(file_of(t), []).append(t)
    files = sorted(by_file)
    out, r = [], 0
    while len(out) < len(suite):
        for f in files:
            if r < len(by_file[f]):
                out.append(by_file[f][r])
        r += 1
    return out


def order_cheapest(suite, cost):
    pos = {t: i for i, t in enumerate(suite)}
    return sorted(suite, key=lambda t: (cost[t], pos[t]))


def coast_d(suite, cost, budget=math.inf):
    """COAST (src/cart/selectors/coast.py) with coverage key = logical test file, no tier, no severity; ties by CI
    order. Exact, linear-time equivalent of COAST's loop: uncovered-file tests first (cheapest that fits), then the
    rest (cheapest that fits); a test that does not fit never fits later because the remaining budget only shrinks."""
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
        # else: an uncovered-file test that does not fit is dropped (it cannot fit later)
    for t in pool:
        if spent + cost[t] <= budget:
            chosen.append(t)
            spent += cost[t]
    return chosen


def plan_greedy(order, cost, budget):
    chosen, spent = [], 0.0
    for t in order:
        if spent + cost[t] <= budget:
            chosen.append(t)
            spent += cost[t]
    return chosen


def time_box(seq, real, budget):
    """Tests completed within `budget` real seconds when `seq` is executed in order (the running test is killed)."""
    out, cum = [], 0.0
    for t in seq:
        cum += real[t]
        if cum > budget:
            break
        out.append(t)
    return out


def apfdc(order, real, D):
    if not D:
        return 0.0
    C = fsum_sorted(real[t] for t in order)
    if C <= 0:
        return 0.0
    before = []
    for t in order:
        if t in D:
            return 1.0 - (fsum_sorted(before) + real[t] / 2.0) / C
        before.append(real[t])
    return 0.0


def first_detection(order, real, D):
    cum = []
    for i, t in enumerate(order):
        cum.append(real[t])
        if t in D:
            return {"rank": i + 1, "cost_s": fsum_sorted(cum)}
    return {"rank": None, "cost_s": None}


# ------------------------------------------------------------------------------------------------ statistics
def wilcoxon_exact_greater(d: list[float]) -> dict:
    """Exact one-sided Wilcoxon signed-rank test (H1: median d > 0); zeros dropped, mid-ranks for ties."""
    nz = [x for x in d if x != 0.0]
    n = len(nz)
    if n == 0:
        return {"n": 0, "W_plus": 0.0, "p": 1.0, "min_achievable_p": 1.0}
    a = sorted(abs(x) for x in nz)
    ranks = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and a[j + 1] == a[i]:
            j += 1
        ranks[a[i]] = (i + j + 2) / 2.0
        i = j + 1
    rk = [ranks[abs(x)] for x in nz]
    wobs = sum(r for r, x in zip(rk, nz) if x > 0)
    cnt = 0
    for signs in itertools.product((0, 1), repeat=n):
        if sum(r for r, s in zip(rk, signs) if s) >= wobs - 1e-12:
            cnt += 1
    return {"n": n, "W_plus": wobs, "p": cnt / 2 ** n, "min_achievable_p": 1 / 2 ** n}


def sign_test_greater(d: list[float]) -> dict:
    w = sum(1 for x in d if x > 0)
    l = sum(1 for x in d if x < 0)
    n = w + l
    p = sum(math.comb(n, i) for i in range(w, n + 1)) / 2 ** n if n else 1.0
    return {"wins": w, "losses": l, "ties": len(d) - n, "p": p}


def mcnemar_exact_greater(a: list[int], b: list[int]) -> dict:
    """a better than b: discordant pairs, exact one-sided binomial."""
    ab = sum(1 for x, y in zip(a, b) if x and not y)
    ba = sum(1 for x, y in zip(a, b) if y and not x)
    n = ab + ba
    p = sum(math.comb(n, i) for i in range(ab, n + 1)) / 2 ** n if n else 1.0
    return {"a_only": ab, "b_only": ba, "p": p, "min_achievable_p": (1 / 2 ** n) if n else 1.0}


def holm(pvals: dict[str, float], alpha: float) -> dict[str, dict]:
    items = sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(items)
    out, running, rejecting = {}, 0.0, True
    for i, (name, p) in enumerate(items):
        adj = min(1.0, max(running, (m - i) * p))
        running = adj
        thr = alpha / (m - i)
        rejecting = rejecting and p < thr
        out[name] = {"p": p, "holm_p": adj, "threshold": thr, "reject": rejecting}
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    def ranks(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2.0
            i = j + 1
        return r
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


# ------------------------------------------------------------------------------------------------ one event
def prepare_event(e: Event, cfg: dict, rule: str = "registered"):
    prun, bcol = _load(e.p_run()), _load(e.b_collect())
    suite, key, bp = build_suite(e, bcol["collected"])
    pdur = p_durations(e, prun)
    sf = speed_factor(e, prun, bcol, cfg["estimator"]["speed_band"])
    est, src = estimator(suite, pdur, int(cfg["estimator"]["unseen_file_min_seen"]), sf["k_applied"], rule)
    total_est = fsum_sorted(est.values())
    fr = list(cfg["budgets"]["fractions_primary"]) + list(cfg["budgets"]["fractions_exploratory"])
    budgets = {str(f): f * total_est for f in fr}
    return dict(prun=prun, bcol=bcol, suite=suite, key=key, bp=bp, pdur=pdur, sf=sf, est=est, src=src,
                total_est=total_est, budgets=budgets)


def lock_record(e: Event, prep: dict) -> dict:
    return {"event_id": e.eid, "P": e.P, "B": e.B, "p_run_sha256": _sha(e.p_run()),
            "b_collect_sha256": _sha(e.b_collect()), "suite_size": len(prep["suite"]),
            "n_backport_ids": len(prep["bp"]), "speed": prep["sf"], "total_est_s": r6(prep["total_est"]),
            "budgets_s": {f: r6(b) for f, b in prep["budgets"].items()}}


def real_costs(e: Event, suite: list[str], est: dict, T: float, override_T: float | None = None):
    passes = []
    for p in e.b_runs():
        if not p.exists():
            continue
        run = _load(p)
        m = {}
        for tid, rec in run["tests"].items():
            lid = e.to_logical(tid)
            if lid is None:
                continue
            dur = (override_T if override_T is not None else T) if rec["outcome"] == "timeout" else float(rec["duration"])
            m[lid] = (rec["outcome"], dur)
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
    per_pass = []
    for pm in passes:
        per_pass.append({t: (pm[t][1] if t in pm else real[t]) for t in suite})
    return real, outs, imputed, per_pass


def detecting_set(e: Event, suite: list[str], outs: dict, bp: set) -> tuple[set, dict]:
    info = {"fcheck_present": e.fcheck().exists()}
    if not e.fcheck().exists():
        return set(), info
    fc = _load(e.fcheck())
    fout = {}
    for part in ("pre_existing", "backport"):
        if fc.get(part):
            for tid, rec in fc[part]["tests"].items():
                lid = e.to_logical(tid)
                if lid is not None:
                    fout[lid] = rec["outcome"]
    D = {t for t in suite if outs.get(t) and all(o in NONPASS for o in outs[t]) and fout.get(t) == "passed"}
    b_nonpass = {t for t in suite if outs.get(t) and all(o in NONPASS for o in outs[t])}
    info.update({"n_detecting": len(D), "n_detecting_backport": len(D & bp), "n_detecting_pre_existing": len(D - bp),
                 "detecting": sorted(D), "b_nonpass_all_passes": len(b_nonpass),
                 "b_nonpass_backport": sorted(b_nonpass & bp),
                 "backport_outcomes_B": {t: outs.get(t) for t in sorted(bp)},
                 "backport_outcomes_F": {t: fout.get(t) for t in sorted(bp)}})
    return D, info


def evaluate_policies(suite, est, real, D, budgets, seeds, fractions, bp=frozenset()):
    """bp: the event's backported (logical) ids. The registered budget-compliance spend (P1) charges the plan's
    PRE-EXISTING tests only (`spend_ratio`), because a backported test's real cost on B is an effect of the fault
    (D7: a 60-s hang priced at a millisecond file median), not of the estimator; `spend_ratio_incl_backport` is
    reported as well (exploratory)."""
    res = {"apfdc": {}, "first": {}, "tiers": {}}
    orders = {"default": order_default(suite), "file_rr": order_file_rr(suite),
              "cheapest_first": order_cheapest(suite, est), "coast_d": coast_d(suite, est),
              "cheapest_oracle": order_cheapest(suite, real)}
    for name, o in orders.items():
        res["apfdc"][name] = r6(apfdc(o, real, D))
        res["first"][name] = first_detection(o, real, D)
    rnd = [r6(apfdc(order_random(suite, s), real, D)) for s in range(seeds)]
    res["apfdc"]["random"] = r6(fsum_sorted(rnd) / len(rnd))
    for f in fractions:
        b = budgets[str(f)]
        tier = {}
        for name in ("default", "file_rr"):
            ex = time_box(orders[name], real, b)
            tier[name] = {"detected": int(bool(set(ex) & D)), "executed": len(ex),
                          "spend_ratio": r6(fsum_sorted(real[t] for t in ex) / b) if b > 0 else None}
            plan = plan_greedy(orders[name], est, b)        # exploratory: cost-blind order, planned with est
            tier[name + "_planned_prefix"] = {"detected_planned": int(bool(set(plan) & D)),
                                              "spend_ratio": r6(fsum_sorted(real[t] for t in plan) / b) if b > 0 else None}
        det = []
        for s in range(seeds):
            ex = time_box(order_random(suite, s), real, b)
            det.append(int(bool(set(ex) & D)))
        tier["random"] = {"detected_prob": r6(sum(det) / len(det))}
        plans = {"cheapest_first": plan_greedy(orders["cheapest_first"], est, b), "coast_d": coast_d(suite, est, b),
                 "cheapest_oracle": plan_greedy(orders["cheapest_oracle"], real, b)}
        for name, plan in plans.items():
            ex = time_box(plan, real, b)
            tier[name] = {"detected": int(bool(set(ex) & D)), "detected_planned": int(bool(set(plan) & D)),
                          "selected": len(plan), "executed": len(ex),
                          "spend_ratio": r6(fsum_sorted(real[t] for t in plan if t not in bp) / b) if b > 0 else None,
                          "spend_ratio_incl_backport": r6(fsum_sorted(real[t] for t in plan) / b) if b > 0 else None,
                          "est_spend_ratio": r6(fsum_sorted(est[t] for t in plan) / b) if b > 0 else None}
        res["tiers"][str(f)] = tier
    return res, orders


def analyse_event(e: Event, cfg: dict) -> dict:
    prep = prepare_event(e, cfg)
    suite, est, bp = prep["suite"], prep["est"], prep["bp"]
    T = float(cfg["runner"]["per_test_timeout_s"])
    real, outs, imputed, per_pass = real_costs(e, suite, est, T)
    D, dinfo = detecting_set(e, suite, outs, bp)
    seeds = int(cfg["policies"]["random_seeds"])
    fr = list(cfg["budgets"]["fractions_primary"]) + list(cfg["budgets"]["fractions_exploratory"])
    pol, orders = evaluate_policies(suite, est, real, D, prep["budgets"], seeds, fr, bp)
    total_real = fsum_sorted(real.values())
    pre_real = fsum_sorted(real[t] for t in suite if t not in bp)
    pre_est = fsum_sorted(est[t] for t in suite if t not in bp)
    # mechanism check M3: coast_d never places the first detecting test earlier than cheapest_first when that test is
    # not the cheapest-estimated test of its file (file-median pricing); reported, never evidence
    m3 = pol["apfdc"]["coast_d"] <= pol["apfdc"]["cheapest_first"]
    # ---- exploratory extras
    seen = [t for t in suite if prep["src"][t] == "seen"]
    big = [t for t in seen if real[t] >= 0.01]
    mape = (statistics.median(abs(est[t] - real[t]) / real[t] for t in big) if big else None)
    unseen_share = fsum_sorted(est[t] for t in suite if prep["src"][t] != "seen") / prep["total_est"] if prep["total_est"] else None
    extras = {
        "n_seen": len(seen), "n_unseen": len(suite) - len(seen), "unseen_est_cost_share": unseen_share,
        "source_counts": {s: sum(1 for t in suite if prep["src"][t] == s) for s in sorted(set(prep["src"].values()))},
        "backport_estimate_source": {t: prep["src"][t] for t in sorted(bp)},
        "backport_est_s": {t: est[t] for t in sorted(bp)}, "backport_real_s": {t: real[t] for t in sorted(bp)},
        "per_test_median_ape_seen_ge_10ms": mape,
        "spearman_est_real_seen": spearman([est[t] for t in seen], [real[t] for t in seen]),
        "n_imputed_real": len(imputed),
    }
    # per-pass spend (noise), alternative unseen rules, timeout sensitivity, default placement at file start
    pp = []
    for k, rp in enumerate(per_pass, 1):
        row = {}
        for f in cfg["budgets"]["fractions_primary"]:
            b = prep["budgets"][str(f)]
            row[str(f)] = {"cheapest_first": r6(fsum_sorted(rp[t] for t in plan_greedy(orders["cheapest_first"], est, b) if t not in bp) / b),
                           "coast_d": r6(fsum_sorted(rp[t] for t in coast_d(suite, est, b) if t not in bp) / b)}
        row["suite_real_s"] = fsum_sorted(rp.values())
        pp.append(row)
    extras["per_pass_spend_ratio"] = pp
    alt = {}
    for rule in ("global_only", "file_mean", "zero"):
        est2, _ = estimator(suite, prep["pdur"], int(cfg["estimator"]["unseen_file_min_seen"]), prep["sf"]["k_applied"], rule)
        tot2 = fsum_sorted(est2.values())
        row = {"apfdc_cheapest_first": r6(apfdc(order_cheapest(suite, est2), real, D)),
               "apfdc_coast_d": r6(apfdc(coast_d(suite, est2), real, D))}
        for f in cfg["budgets"]["fractions_primary"]:
            b = f * tot2
            plan = coast_d(suite, est2, b)
            row[str(f)] = {"coast_d_detected": int(bool(set(time_box(plan, real, b)) & D)),
                           "coast_d_spend_ratio": r6(fsum_sorted(real[t] for t in plan if t not in bp) / b) if b else None}
        alt[rule] = row
    extras["unseen_rule_alternatives"] = alt
    real10, _, _, _ = real_costs(e, suite, est, T, override_T=10.0)
    extras["timeout_10s_apfdc"] = {"default": r6(apfdc(orders["default"], real10, D)),
                                   "coast_d": r6(apfdc(orders["coast_d"], real10, D))}
    alts = alt_default_orders(suite, prep["key"], bp)
    extras["default_variants_apfdc"] = {k: r6(apfdc(o, real, D)) for k, o in sorted(alts.items())}
    extras["default_variants_first_detection"] = {k: first_detection(o, real, D) for k, o in sorted(alts.items())}
    extras["mechanism_M3_coast_le_cheapest_first"] = m3
    extras["backport_default_rank"] = {t: suite.index(t) + 1 for t in sorted(bp)}
    return {
        "event_id": e.eid, "P": e.P, "B": e.B, "F": e.F, "suite_size": len(suite), "n_backport_ids": len(bp),
        "backport_id_collisions": backport_collisions(e, prep["bcol"]["collected"]),
        "speed": prep["sf"], "total_est_s": r6(prep["total_est"]), "total_real_s": r6(total_real),
        "pre_existing_est_s": r6(pre_est), "pre_existing_real_s": r6(pre_real),
        "suite_cost_rel_error": r6(pre_est / pre_real - 1.0) if pre_real else None,
        "suite_cost_rel_error_incl_backport": r6(prep["total_est"] / total_real - 1.0) if total_real else None,
        "budgets_s": {f: r6(b) for f, b in prep["budgets"].items()},
        "detection": dinfo, "policies": pol, "exploratory": extras, "_lock": lock_record(e, prep),
    }


# ------------------------------------------------------------------------------------------------ study level
def decide(results: list[dict], cfg: dict) -> dict:
    """Confirmatory family: P1, P2 (decision rules). H1, H2 and D1 are REGISTERED FORECAST CHECKS (computed exactly
    as specified, reported whatever the outcome, no confirmatory claim): a prior-predictive check from pre-record
    observations showed them near-certain by construction (PREREGISTRATION_PHASE_D.md, Sections 9.2 and 10)."""
    C = {**cfg["confirmatory"], **cfg["forecast_checks"]}
    out = {"roles": {"confirmatory": sorted(k for k in cfg["confirmatory"] if k != "note"),
                     "forecast_checks": sorted(k for k in cfg["forecast_checks"] if k != "note")}}
    # P1 budget compliance
    crit = {}
    for pol in C["P1"]["policies"]:
        for f in C["P1"]["fractions"]:
            rs = [r["policies"]["tiers"][str(f)][pol]["spend_ratio"] for r in results]
            m, mx = fsum_sorted(rs) / len(rs), max(rs)
            crit[f"{pol}@{f}"] = {"mean": r6(m), "max": r6(mx),
                                  "holds": m <= C["P1"]["mean_spend_ratio_max"] and mx <= C["P1"]["single_event_spend_ratio_max"]}
    out["P1"] = {"criteria": crit, "supported": all(v["holds"] for v in crit.values())}
    # P2 suite-cost estimate
    errs = {r["event_id"]: r["suite_cost_rel_error"] for r in results}
    out["P2"] = {"rel_error": errs, "supported": all(v is not None and abs(v) <= C["P2"]["abs_rel_error_max"] for v in errs.values())}
    # H1/H2 Wilcoxon + Holm
    tests, pv = {}, {}
    for h, (a, b) in sorted(C["H"]["tests"].items()):
        d = [r6(r["policies"]["apfdc"][a] - r["policies"]["apfdc"][b]) for r in results]
        w = wilcoxon_exact_greater(d)
        tests[h] = {"a": a, "b": b, "d": d, "mean_d": r6(fsum_sorted(d) / len(d)), "wilcoxon": w,
                    "sign_test": sign_test_greater(d)}
        pv[h] = w["p"]
    hh = holm(pv, C["H"]["alpha_familywise"])
    for h in tests:
        tests[h]["holm"] = hh[h]
        tests[h]["supported"] = hh[h]["reject"] and tests[h]["mean_d"] > 0
    out["H"] = tests
    # D1 detection within budget (decision rule)
    d1 = {}
    for f in C["D1"]["fractions"]:
        t = [r["policies"]["tiers"][str(f)] for r in results]
        cnt = {"coast_d": sum(x["coast_d"]["detected"] for x in t), "default": sum(x["default"]["detected"] for x in t),
               "file_rr": sum(x["file_rr"]["detected"] for x in t),
               "random_expected": r6(fsum_sorted(x["random"]["detected_prob"] for x in t))}
        d1[str(f)] = {"counts": cnt,
                      "geq_all": cnt["coast_d"] >= cnt["default"] and cnt["coast_d"] >= cnt["file_rr"]
                      and cnt["coast_d"] >= cnt["random_expected"] - 1e-9,
                      "gt_default": cnt["coast_d"] > cnt["default"],
                      "mcnemar_vs_default": mcnemar_exact_greater([x["coast_d"]["detected"] for x in t],
                                                                 [x["default"]["detected"] for x in t])}
    out["D1"] = {"tiers": d1, "supported": all(v["geq_all"] for v in d1.values()) and any(v["gt_default"] for v in d1.values())}
    return out


def cluster_sensitivity(results: list[dict], cfg: dict) -> dict:
    """Exploratory: events sharing a B release averaged into one cluster before the Wilcoxon test."""
    out = {}
    for h, (a, b) in sorted(cfg["forecast_checks"]["H"]["tests"].items()):
        cl: dict[str, list[float]] = {}
        for r in results:
            cl.setdefault(r["B"], []).append(r["policies"]["apfdc"][a] - r["policies"]["apfdc"][b])
        d = [r6(fsum_sorted(v) / len(v)) for _, v in sorted(cl.items())]
        out[h] = {"clusters": len(d), "d": d, "wilcoxon": wilcoxon_exact_greater(d)}
    return out


def load_ctx(args):
    cfg = _load(Path(args.config))
    ledger = _load(Path(args.ledger))
    data = Path(args.data)
    return cfg, ledger, data


def leakage_checks(ledger: dict, cfg: dict) -> list[dict]:
    out = []
    vs = {**cfg.get("versions", {}), **cfg.get("dryrun_versions_outside_study", {})}
    for ev in ledger["events"]:
        P, B = ev["P"], ev["B"]
        out.append({"event_id": ev["event_id"], "P_ne_B": P != B,
                    "P_uploaded_before_B": (vs[P]["upload_time_utc"] < vs[B]["upload_time_utc"]) if P in vs and B in vs else None})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(REPO / "phase_d/config/phase_d_config.json"))
    ap.add_argument("--ledger", default=str(REPO / "phase_d/events/phase_d_events.json"))
    ap.add_argument("--data", default=str(REPO / "phase_d/data/assembled"))
    ap.add_argument("--locks", default=str(REPO / "phase_d/data/budget_lock"))
    ap.add_argument("--out", default=str(REPO / "results/phase_d_confirmatory.json"))
    ap.add_argument("--lock", nargs="*", help="write budget locks for these events (before their B runs)")
    args = ap.parse_args()
    cfg, ledger, data = load_ctx(args)
    events = [Event(ev, cfg, data) for ev in ledger["events"]]
    locks = Path(args.locks)
    if args.lock is not None:
        locks.mkdir(parents=True, exist_ok=True)
        for e in events:
            if e.eid in args.lock:
                raw = data.parent / "runs" / f"w{e.B}_t{e.B}"
                if any(p.exists() for p in e.b_runs()) or (raw.exists() and any(raw.rglob("*"))):
                    raise SystemExit(f"{e.eid}: B timing data of {e.B} already exist (assembled or raw); "
                                     "the lock must precede B runs")
                rec = lock_record(e, prepare_event(e, cfg))
                lk = locks / f"{e.eid}.json"
                if lk.exists():
                    old = _load(lk)
                    if {k: old.get(k) for k in rec} != rec:
                        raise SystemExit(f"{e.eid}: a different budget lock already exists; locks are never rewritten")
                    print(json.dumps({"unchanged": str(lk)}))
                    continue
                rec["locked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                rec["analysis_sha256"] = _sha(Path(__file__))
                lk.write_text(json.dumps(rec, indent=1, sort_keys=True))
                print(json.dumps(rec, sort_keys=True))
        return
    results, deviations = [], []
    excluded = []
    for e in events:
        missing = [str(p.name) for p in [e.p_run(), e.b_collect()] + e.b_runs() if not p.exists()]
        if len(missing) == len(e.b_runs()) + 2 or not e.p_run().exists() or not e.b_collect().exists() \
                or not any(p.exists() for p in e.b_runs()):
            excluded.append({"event_id": e.eid, "missing": missing})
            deviations.append(f"{e.eid}: excluded (missing {', '.join(missing)})")
            continue
        r = analyse_event(e, cfg)
        lk = locks / f"{e.eid}.json"
        lock = r.pop("_lock")
        if lk.exists():
            frozen = _load(lk)
            r["budget_lock_matches"] = (frozen["budgets_s"] == lock["budgets_s"]
                                        and frozen["p_run_sha256"] == lock["p_run_sha256"]
                                        and frozen["b_collect_sha256"] == lock["b_collect_sha256"])
            if not r["budget_lock_matches"]:
                deviations.append(f"{e.eid}: budget lock mismatch")
        else:
            r["budget_lock_matches"] = None
            deviations.append(f"{e.eid}: no budget lock")
        if not r["detection"]["fcheck_present"]:
            deviations.append(f"{e.eid}: F-check missing (no detecting test can be established)")
        if r["backport_id_collisions"]:
            deviations.append(f"{e.eid}: backported ids coincide with pre-existing B ids: {r['backport_id_collisions']}")
        if r["exploratory"]["n_imputed_real"]:
            deviations.append(f"{e.eid}: {r['exploratory']['n_imputed_real']} suite tests without a B record (charged est)")
        results.append(r)
    if not results:
        raise SystemExit("no analysable event")
    out = {"schema": "phase_d_confirmatory/1", "events": results, "excluded_events": excluded,
           "decisions": decide(results, cfg),
           "exploratory_cluster_sensitivity": cluster_sensitivity(results, cfg),
           "leakage_checks": leakage_checks(ledger, cfg), "deviations": deviations,
           "inputs_sha256": {p.name: _sha(p) for p in sorted(data.glob("*.json"))},
           "analysis_sha256": _sha(Path(__file__))}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({"wrote": args.out, "confirmatory": {"P1": out["decisions"]["P1"]["supported"],
                                                          "P2": out["decisions"]["P2"]["supported"]},
                      "forecast_checks": {**{h: v["supported"] for h, v in out["decisions"]["H"].items()},
                                          "D1": out["decisions"]["D1"]["supported"]},
                      "deviations": deviations}))


if __name__ == "__main__":
    main()
