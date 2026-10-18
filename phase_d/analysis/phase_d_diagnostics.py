"""EXPLORATORY / POST HOC diagnostics of Phase D (NOT part of the pre-registered, frozen analysis).

Written 2026-10-18, AFTER the one confirmatory run (results/phase_d_confirmatory.json) showed P1 and P2 failing.
Nothing here is confirmatory. The "corrections" evaluated below were chosen after seeing the data; they are reported
only to describe mechanisms and to suggest rules that a future study would have to pre-register and test on new events.

Reads only: phase_d/data/assembled/*.json, phase_d/data/runs/*/pass*/files/*.{jsonl,done.json} (raw per-phase timings),
phase_d/config, phase_d/events, results/phase_d_confirmatory.json, data_scaleup/derived/labels.json.
Writes:     results/phase_d_exploratory_diagnostics.json   (never touches frozen files or phase_d/data/)
Does not import phase_d_analysis.py (independent re-implementation of the registered estimator; checked against the
confirmatory results file in section "consistency").  Standard library only; deterministic.

    python phase_d/analysis/phase_d_diagnostics.py
"""
from __future__ import annotations

import collections
import glob
import json
import math
import statistics
from pathlib import Path

R = Path(__file__).resolve().parents[2]
A = R / "phase_d/data/assembled"
RUNS = R / "phase_d/data/runs"
CFG = json.loads((R / "phase_d/config/phase_d_config.json").read_text())
EVS = json.loads((R / "phase_d/events/phase_d_events.json").read_text())["events"]
CONF = json.loads((R / "results/phase_d_confirmatory.json").read_text())
BP = CFG["slice"]["backport_dir"] + "/"
T = float(CFG["runner"]["per_test_timeout_s"])
FR = (0.05, 0.25)
OUT = R / "results/phase_d_exploratory_diagnostics.json"


def ld(p):
    return json.loads(Path(p).read_text())


def fil(t):
    return t.split("::", 1)[0]


def r4(x):
    return None if x is None else round(float(x), 4)


def fs(xs):
    return math.fsum(sorted(xs))


_runs: dict = {}


def run(v, k):
    if (v, k) not in _runs:
        p = A / f"run_w{v}_t{v}_pass{k}.json"
        _runs[(v, k)] = ld(p)["tests"] if p.exists() else None
    return _runs[(v, k)]


def dur(rec):
    return T if rec["outcome"] == "timeout" else float(rec["duration"])


def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return None
    i = q * (len(s) - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def spearman(x, y):
    def rk(v):
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
    rx, ry = rk(x), rk(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


# ------------------------------------------------------------------ registered estimator, re-implemented
def build(ev):
    P, B = ev["P"], ev["B"]
    own = BP + Path(ev["backport_file"]).name

    def lg(t):
        f = fil(t)
        if f.startswith(BP):
            return ev["logical_file"] + "::" + t.split("::", 1)[1] if f == own else None
        return t
    # CI order (needed only for tie-breaks): take it from the frozen results' detection-free reconstruction:
    # files sorted, B collection order; backported tests placed by the registered method-name rule.
    coll = ld(A / f"collect_{B}.json")["collected"]
    pre, bpl = [], []
    for i, t in enumerate(coll):
        l = lg(t)
        if l is None:
            continue
        (bpl if l != t else pre).append((l, i))
    key = {t: (fil(t), i, 0, i) for t, i in pre}
    cls = collections.defaultdict(list)
    for t, i in pre:
        cls[t.rsplit("::", 1)[0]].append((t.rsplit("::", 1)[1], i))
    for b, i in bpl:
        if b in key:
            continue
        mem, m = cls.get(b.rsplit("::", 1)[0], []), b.rsplit("::", 1)[1]
        lo = [j for n, j in mem if n < m]
        key[b] = (fil(b), max(lo), 1, i) if lo else ((fil(b), min(j for _, j in mem), -1, i) if mem else (fil(b), math.inf, 1, i))
    suite = sorted(key, key=key.get)
    bps = {b for b, _ in bpl}
    pd = {t: dur(r) for t, r in run(P, 1).items() if not fil(t).startswith(BP)}
    byf = collections.defaultdict(list)
    for t, d in pd.items():
        byf[fil(t)].append(d)
    gmed = statistics.median(pd.values())
    est, src = {}, {}
    for t in suite:
        if t in pd:
            est[t], src[t] = pd[t], "seen"
        elif len(byf[fil(t)]) >= 3:
            est[t], src[t] = statistics.median(byf[fil(t)]), "file_median"
        else:
            est[t], src[t] = gmed, "global_median"
    passes = []
    for k in (1, 2):
        m = {}
        for t, rec in run(B, k).items():
            l = lg(t)
            if l:
                m[l] = dur(rec)
        passes.append(m)
    real = {t: fs([m[t] for m in passes if t in m]) / sum(1 for m in passes if t in m) for t in suite}
    tot = fs(est.values())
    return dict(ev=ev, suite=suite, bps=bps, pd=pd, byf=byf, gmed=gmed, est=est, src=src, passes=passes, real=real,
                tot=tot, budgets={f: f * tot for f in FR}, lg=lg)


def order_cheapest(suite, cost):
    pos = {t: i for i, t in enumerate(suite)}
    return sorted(suite, key=lambda t: (cost[t], pos[t]))


def greedy(order, cost, b):
    out, s = [], 0.0
    for t in order:
        if s + cost[t] <= b:
            out.append(t)
            s += cost[t]
    return out


def coast_d(suite, cost, b=math.inf):
    srt = order_cheapest(suite, cost)
    cov, out, rest, s = set(), [], [], 0.0
    for t in srt:
        if fil(t) in cov:
            rest.append(t)
        elif s + cost[t] <= b:
            out.append(t)
            s += cost[t]
            cov.add(fil(t))
    for t in rest:
        if s + cost[t] <= b:
            out.append(t)
            s += cost[t]
    return out


def spend(E, plan, b, real=None):
    real = real or E["real"]
    return fs(real[t] for t in plan if t not in E["bps"]) / b


# ------------------------------------------------------------------ (a) P2: per-file decomposition
def p2_files(E, top=6):
    est, real, bps = E["est"], E["real"], E["bps"]
    fe, fr, fn, fsrc = collections.defaultdict(float), collections.defaultdict(float), collections.Counter(), collections.defaultdict(collections.Counter)
    for t in E["suite"]:
        if t in bps:
            continue
        f = fil(t)
        fe[f] += est[t]
        fr[f] += real[t]
        fn[f] += 1
        fsrc[f][E["src"][t]] += 1
    pe, pr = fs(fe.values()), fs(fr.values())
    gap = pe - pr
    rows = sorted(fe, key=lambda f: -abs(fe[f] - fr[f]))
    out = []
    for f in rows[:top]:
        out.append({"file": f, "n": fn[f], "est_s": r4(fe[f]), "real_s": r4(fr[f]), "est_minus_real_s": r4(fe[f] - fr[f]),
                    "share_of_net_gap": r4((fe[f] - fr[f]) / gap) if gap else None, "est_sources": dict(fsrc[f])})
    top2 = rows[:2]
    ex_e = pe - sum(fe[f] for f in top2)
    ex_r = pr - sum(fr[f] for f in top2)
    # tests removed between P and B (in P, not in the B suite) and new tests (in B, not in P)
    pset, sset = set(E["pd"]), set(t for t in E["suite"] if t not in bps)
    removed = pset - sset
    return {"pre_est_s": r4(pe), "pre_real_s": r4(pr), "rel_error": r4(pe / pr - 1), "top_files": out,
            "rel_error_excluding_top2_files": r4(ex_e / ex_r - 1) if ex_r else None,
            "P_tests_removed_in_B": len(removed), "P_cost_of_removed_s": r4(fs(E["pd"][t] for t in removed)),
            "B_tests_unseen_in_P": len(sset - pset),
            "B_unseen_est_s": r4(fs(E["est"][t] for t in sset - pset)),
            "B_unseen_real_s": r4(fs(E["real"][t] for t in sset - pset)),
            "seen_tests_est_s": r4(fs(E["est"][t] for t in sset & pset)),
            "seen_tests_real_s": r4(fs(E["real"][t] for t in sset & pset))}


def outcome_change(E, f):
    """Outcome mix of the pre-existing tests of file f on P and on B pass 1 (e.g. a whole file newly skipped)."""
    P, B = E["ev"]["P"], E["ev"]["B"]
    po = collections.Counter(r["outcome"] for t, r in run(P, 1).items() if fil(t) == f)
    bo = collections.Counter(r["outcome"] for t, r in run(B, 1).items() if fil(t) == f)
    return {"P": dict(po), "B_pass1": dict(bo)}


# ------------------------------------------------------------------ (b) P1 mechanisms
def p1_decomposition(E):
    est, real = E["est"], E["real"]
    out = {}
    for f in FR:
        b = E["budgets"][f]
        plan = [t for t in greedy(order_cheapest(E["suite"], est), est, b) if t not in E["bps"]]
        g = collections.defaultdict(lambda: [0, 0.0, 0.0])
        for t in plan:
            x = g[E["src"][t]]
            x[0] += 1
            x[1] += est[t]
            x[2] += real[t]
        out[str(f)] = {"spend_ratio": r4(fs(real[t] for t in plan) / b),
                       "by_estimate_source": {s: {"n": v[0], "est_over_budget": r4(v[1] / b), "real_over_budget": r4(v[2] / b),
                                                  "real_over_est": r4(v[2] / v[1]) if v[1] else None} for s, v in sorted(g.items())}}
        # the unseen tests' files that carry the most real cost inside the plan
        uf = collections.defaultdict(lambda: [0, 0.0, 0.0])
        for t in plan:
            if E["src"][t] != "seen":
                x = uf[fil(t)]
                x[0] += 1
                x[1] += est[t]
                x[2] += real[t]
        out[str(f)]["top_unseen_files_in_plan"] = [{"file": k, "n": v[0], "est_s": r4(v[1]), "real_s": r4(v[2])}
                                                   for k, v in sorted(uf.items(), key=lambda kv: -kv[1][2])[:3]]
    return out


def winners_curse(E):
    """Seen tests only. (1) real/est for the 5%-plan's seen tests vs the remaining seen tests (regression to the
    mean on P->B). (2) within-B self-selection: plan with B pass-1 durations (5%/25% of pass-1 total), charge pass 2:
    pure measurement noise + selection, same code and machine."""
    est, real = E["est"], E["real"]
    seen = [t for t in E["suite"] if E["src"][t] == "seen" and t not in E["bps"]]
    b = E["budgets"][0.05]
    plan = set(greedy(order_cheapest(E["suite"], est), est, b))
    sel = [t for t in seen if t in plan]
    non = [t for t in seen if t not in plan]
    res = {"seen_selected_real_over_est_5pct": r4(fs(real[t] for t in sel) / fs(est[t] for t in sel)),
           "seen_not_selected_real_over_est_5pct": r4(fs(real[t] for t in non) / fs(est[t] for t in non)) if non else None,
           "spearman_P_vs_Bmean_seen": r4(spearman([est[t] for t in seen], [real[t] for t in seen]))}
    p1, p2 = E["passes"]
    pre = [t for t in E["suite"] if t not in E["bps"] and t in p1 and t in p2]
    res["spearman_Bpass1_vs_Bpass2"] = r4(spearman([p1[t] for t in pre], [p2[t] for t in pre]))
    tot1 = fs(p1[t] for t in pre)
    for f in FR:
        bb = f * tot1
        pl = greedy(order_cheapest(pre, p1), p1, bb)
        res[f"self_selection_pass1_to_pass2_spend_{f}"] = r4(fs(p2[t] for t in pl) / bb)
    # P -> B restricted to seen tests with the budget recomputed over seen tests only (no cold-start effect)
    tots = fs(est[t] for t in seen)
    for f in FR:
        bb = f * tots
        pl = greedy(order_cheapest(seen, est), est, bb)
        res[f"seen_only_P_to_B_spend_{f}"] = r4(fs(real[t] for t in pl) / bb)
    return res


_raw_cache: dict = {}


def raw_phases(v):
    """setup/call/teardown per test id of B pass 1 (raw jsonl) and per-file wall time vs sum of durations."""
    if v in _raw_cache:
        return _raw_cache[v]
    ph, wall, dsum = {}, 0.0, 0.0
    for p in sorted(glob.glob(str(RUNS / f"w{v}_t{v}" / "pass1" / "files" / "*.jsonl"))):
        for line in open(p):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("ev") == "done":
                ph[r["id"]] = (r.get("setup") or 0.0, r.get("call") or 0.0, r.get("teardown") or 0.0)
                dsum += float(r.get("duration") or 0.0)
    for p in sorted(glob.glob(str(RUNS / f"w{v}_t{v}" / "pass1" / "files" / "*.done.json"))):
        wall += float(ld(p).get("wall_s_this_call") or 0.0)
    _raw_cache[v] = (ph, wall, dsum)
    return _raw_cache[v]


def overhead(E):
    """(ii) fixed per-test overhead. Setup+teardown share of the 5%-plan's real cost; intercept-like quantity
    (median real - est among the cheapest-decile seen tests); and wall-clock vs summed durations (process start,
    imports, collection, reporting: in NEITHER est nor real, so it does not bias P1 as defined, but a CI time box
    would pay it)."""
    B = E["ev"]["B"]
    ph, wall, dsum = raw_phases(B)
    est, real = E["est"], E["real"]
    b = E["budgets"][0.05]
    plan = [t for t in greedy(order_cheapest(E["suite"], est), est, b) if t not in E["bps"]]
    st = fs(ph[t][0] + ph[t][2] for t in plan if t in ph)
    tt = fs(sum(ph[t]) for t in plan if t in ph)
    seen = sorted((t for t in E["suite"] if E["src"][t] == "seen" and t not in E["bps"]), key=lambda t: est[t])
    dec = seen[: max(1, len(seen) // 10)]
    return {"plan5_setup_teardown_share_Bpass1": r4(st / tt) if tt else None,
            "cheapest_decile_seen_median_est_s": r4(statistics.median(est[t] for t in dec)),
            "cheapest_decile_seen_median_real_s": r4(statistics.median(real[t] for t in dec)),
            "cheapest_decile_seen_median_real_minus_est_s": r4(statistics.median(real[t] - est[t] for t in dec)),
            "B_pass1_wall_s": r4(wall), "B_pass1_sum_durations_s": r4(dsum),
            "B_pass1_wall_over_sum_durations": r4(wall / dsum) if dsum else None}


# ------------------------------------------------------------------ post hoc corrections
def variants(E):
    """Alternative planning costs (POST HOC). The registered budget in seconds is kept fixed (the CI time box);
    only the planner's cost changes; spend = real cost of the plan's pre-existing tests / registered budget.
    'rebudget' rows also recompute the budget as f * sum(alternative est) (estimator-consistent CI)."""
    est, pd, byf, suite = E["est"], E["pd"], E["byf"], E["suite"]
    allp = list(pd.values())
    gmean = fs(allp) / len(allp)
    gp90 = quantile(allp, 0.90)
    fmean = {f: fs(v) / len(v) for f, v in byf.items() if v}
    fmed = {f: statistics.median(v) for f, v in byf.items() if v}
    unseen = {t for t in suite if E["src"][t] != "seen"}

    def unseen_mean(t):
        f = fil(t)
        return fmean[f] if len(byf.get(f, [])) >= 3 else gmean

    alt = {
        "registered": dict(est),
        "unseen_at_mean (file mean if >=3 seen, else global mean)": {t: (unseen_mean(t) if t in unseen else est[t]) for t in suite},
        "unseen_at_global_p90": {t: (gp90 if t in unseen else est[t]) for t in suite},
        "floor_at_P_median (all tests)": {t: max(est[t], E["gmed"]) for t in suite},
        "shrink_half_to_file_median (seen)": {t: (0.5 * est[t] + 0.5 * fmed[fil(t)] if t not in unseen else est[t]) for t in suite},
    }
    alt["unseen_at_mean + shrink"] = {t: (alt["unseen_at_mean (file mean if >=3 seen, else global mean)"][t] if t in unseen
                                          else 0.5 * est[t] + 0.5 * fmed[fil(t)]) for t in suite}
    res = {}
    for name, c in alt.items():
        row = {}
        for f in FR:
            b = E["budgets"][f]
            p_cf = greedy(order_cheapest(suite, c), c, b)
            p_cd = coast_d(suite, c, b)
            b2 = f * fs(c.values())
            row[str(f)] = {"cheapest_first": r4(spend(E, p_cf, b)), "coast_d": r4(spend(E, p_cd, b)),
                           "n_selected_cf": len(p_cf),
                           "rebudget_cheapest_first": r4(spend(E, greedy(order_cheapest(suite, c), c, b2), b2))}
        res[name] = row
    # unseen tests run in a separate always-run lane: plan seen tests only under the registered budget
    seen = [t for t in suite if t not in unseen]
    row = {}
    for f in FR:
        b = E["budgets"][f]
        row[str(f)] = {"cheapest_first": r4(spend(E, greedy(order_cheapest(seen, est), est, b), b)),
                       "coast_d": r4(spend(E, coast_d(seen, est, b), b)),
                       "always_run_lane_real_s": r4(fs(E["real"][t] for t in unseen if t not in E["bps"])),
                       "always_run_lane_over_budget": r4(fs(E["real"][t] for t in unseen if t not in E["bps"]) / b)}
    res["unseen_in_separate_always_run_lane"] = row
    # file-level budgeting: whole files, cheapest estimated file first (greedy with skip)
    fe = collections.defaultdict(float)
    for t in suite:
        fe[fil(t)] += alt["unseen_at_mean (file mean if >=3 seen, else global mean)"][t]
    fe_reg = collections.defaultdict(float)
    for t in suite:
        fe_reg[fil(t)] += est[t]
    for name, fc in (("file_level_registered_est", fe_reg), ("file_level_unseen_at_mean", fe)):
        row = {}
        for f in FR:
            b = E["budgets"][f]
            chosen, s = [], 0.0
            for fl in sorted(fc, key=lambda x: (fc[x], x)):
                if s + fc[fl] <= b:
                    chosen.append(fl)
                    s += fc[fl]
            cs = set(chosen)
            plan = [t for t in suite if fil(t) in cs]
            row[str(f)] = {"spend": r4(spend(E, plan, b)), "n_files": len(chosen), "n_tests": len(plan)}
        res[name] = row
    return res


def summarize_variants(per_event):
    names = list(next(iter(per_event.values())).keys())
    out = {}
    for n in names:
        row = {}
        for f in FR:
            for pol in ("cheapest_first", "coast_d", "spend", "rebudget_cheapest_first"):
                xs = [per_event[e][n][str(f)].get(pol) for e in per_event]
                if all(x is not None for x in xs):
                    row[f"{pol}@{f}"] = {"mean": r4(sum(xs) / len(xs)), "max": r4(max(xs)),
                                         "would_meet_P1_thresholds": (sum(xs) / len(xs) <= 1.25 and max(xs) <= 2.0)}
        out[n] = row
    return out


# ------------------------------------------------------------------ (c) heavy tails
def tail_stats(xs):
    s = sorted(xs, reverse=True)
    tot = fs(s)
    n = len(s)

    def top(p):
        k = max(1, int(math.ceil(p * n)))
        return fs(s[:k]) / tot
    asc = s[::-1]
    gini = (2 * sum((i + 1) * x for i, x in enumerate(asc)) / (n * tot) - (n + 1) / n) if tot else None
    return {"n": n, "total_s": r4(tot), "top1pct_share": r4(top(0.01)), "top5pct_share": r4(top(0.05)),
            "top10pct_share": r4(top(0.10)), "max_over_median": r4(s[0] / statistics.median(s)) if statistics.median(s) else None,
            "median_s": r4(statistics.median(s)), "gini": r4(gini)}


def synthetic_tails():
    lab = ld(R / "data_scaleup/derived/labels.json")["labels"]
    by = collections.defaultdict(list)
    for x in lab:
        if isinstance(x.get("total_cost_s"), (int, float)):
            by[x["event_id"]].append(x["total_cost_s"])
    per = {e: tail_stats(v) for e, v in by.items() if len(v) >= 5}
    keys = ("top1pct_share", "top5pct_share", "top10pct_share", "gini")
    med = {k: r4(statistics.median(p[k] for p in per.values())) for k in keys}
    pooled = tail_stats([v for vs in by.values() for v in vs])
    return {"n_events": len(per), "median_over_events": med, "median_suite_size": statistics.median(p["n"] for p in per.values()),
            "median_suite_total_s": r4(statistics.median(p["total_s"] for p in per.values())), "pooled": pooled}


# ------------------------------------------------------------------ (d) detecting tests
def detecting(E, conf_ev):
    D = conf_ev["detection"]["detecting"]
    est, real, suite = E["est"], E["real"], E["suite"]
    o_cf = order_cheapest(suite, est)
    o_cd = coast_d(suite, est)
    pos = {"default": {t: i + 1 for i, t in enumerate(suite)}, "cheapest_first": {t: i + 1 for i, t in enumerate(o_cf)},
           "coast_d": {t: i + 1 for i, t in enumerate(o_cd)}}
    plans = {f: {"cheapest_first": set(greedy(o_cf, est, E["budgets"][f])), "coast_d": set(coast_d(suite, est, E["budgets"][f]))} for f in FR}
    rows = []
    for t in D:
        rows.append({"test": t, "est_s": r4(est[t]), "real_s": r4(real[t]), "est_source": E["src"][t],
                     "B_outcomes": conf_ev["detection"]["backport_outcomes_B"].get(t),
                     "rank": {k: pos[k][t] for k in pos}, "suite_size": len(suite),
                     "in_plan": {str(f): {k: (t in plans[f][k]) for k in plans[f]} for f in FR}})
    tiers = conf_ev["policies"]["tiers"]
    return {"detecting_tests": rows, "first_detection_frozen": conf_ev["policies"]["first"],
            "detected_within_time_box_frozen": {f: {k: tiers[f][k].get("detected", tiers[f][k].get("detected_prob"))
                                                    for k in ("default", "random", "cheapest_first", "coast_d")} for f in ("0.05", "0.25")}}


# ------------------------------------------------------------------ main
def main():
    conf = {r["event_id"]: r for r in CONF["events"]}
    out = {"schema": "phase_d_exploratory_diagnostics/1",
           "STATUS": "EXPLORATORY / POST HOC. Written after the confirmatory run; no result here is confirmatory. "
                     "Corrections were chosen after seeing the data and must be pre-registered and tested on new events.",
           "consistency": {}, "events": {}}
    pv = {}
    synthetic = synthetic_tails()
    for ev in EVS:
        e = ev["event_id"]
        E = build(ev)
        c = conf[e]
        chk = {"P2_rel_error_matches": abs((E and (fs(E['est'][t] for t in E['suite'] if t not in E['bps']) /
                                                   fs(E['real'][t] for t in E['suite'] if t not in E['bps']) - 1)) - c["suite_cost_rel_error"]) < 1e-5,
               "P1_cf05_matches": abs(spend(E, greedy(order_cheapest(E["suite"], E["est"]), E["est"], E["budgets"][0.05]), E["budgets"][0.05])
                                      - c["policies"]["tiers"]["0.05"]["cheapest_first"]["spend_ratio"]) < 1e-5}
        out["consistency"][e] = chk
        p2 = p2_files(E)
        for row in p2["top_files"][:2]:
            row["outcomes"] = outcome_change(E, row["file"])
        v = variants(E)
        pv[e] = v
        out["events"][e] = {
            "P": ev["P"], "B": ev["B"], "speed_factor_k_measured": r4(c["speed"]["k_measured"]),
            "k_applied": c["speed"]["k_applied"],
            "a_P2_decomposition": p2,
            "b_P1_decomposition": p1_decomposition(E),
            "b_winners_curse_and_noise": winners_curse(E),
            "b_fixed_overhead": overhead(E),
            "b_post_hoc_variants": v,
            "c_tail_B_real_pre_existing": tail_stats([E["real"][t] for t in E["suite"] if t not in E["bps"]]),
            "c_tail_P_durations": tail_stats(list(E["pd"].values())),
            "d_detecting": detecting(E, c),
        }
    out["b_post_hoc_variants_summary"] = summarize_variants(pv)
    out["c_synthetic_corpus_tails (data_scaleup labels total_cost_s, per event)"] = synthetic
    out["c_phase_d_tails_median_over_events"] = {k: r4(statistics.median(out["events"][e]["c_tail_B_real_pre_existing"][k] for e in out["events"]))
                                                 for k in ("top1pct_share", "top5pct_share", "top10pct_share", "gini")}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({"wrote": str(OUT), "consistency_all_ok": all(all(v.values()) for v in out["consistency"].values())}))


if __name__ == "__main__":
    main()
