"""EXPLORATORY / POST HOC diagnostics of Phase E (NOT part of the pre-registered, frozen analysis).

Written 2026-10-19, AFTER the one confirmatory run (results/phase_e_confirmatory.json) showed P1' NOT supported (failure
from pair E2, 1.0.2 -> 1.1.0, at 5% and 25%) and P2' supported. Nothing here is confirmatory. Every quantity below was
chosen after seeing the data; it describes mechanisms only. Any "what if" number (e.g. the spend ratio without the
single worst test) is a sensitivity description, not a corrected result.

Reads only: phase_e/data/assembled/*.json, phase_e/data/runs/*/pass*/files/*.jsonl (raw setup/call/teardown),
phase_e/config, phase_e/events, results/phase_e_confirmatory.json.
Writes:     results/phase_e_exploratory_diagnostics.json   (never touches frozen files or phase_e/data/)
Does not import phase_e_analysis.py: the estimator and plans are re-implemented here (as in Phase D's diagnostics) and
checked against the confirmatory results file (section "consistency"). Standard library only; deterministic.

    python phase_e/analysis/phase_e_diagnostics.py
"""
from __future__ import annotations

import collections
import glob
import json
import math
import statistics
from pathlib import Path

R = Path(__file__).resolve().parents[2]
A = R / "phase_e/data/assembled"
RUNS = R / "phase_e/data/runs"
CFG = json.loads((R / "phase_e/config/phase_e_config.json").read_text())
PAIRS = json.loads((R / "phase_e/events/phase_e_pairs.json").read_text())["events"]
CONF = json.loads((R / "results/phase_e_confirmatory.json").read_text())
T = float(CFG["runner"]["per_test_timeout_s"])
FR = (0.05, 0.25)
POL = ("cheapest_first", "coast_d")
OUT = R / "results/phase_e_exploratory_diagnostics.json"
SPECS = {"primary": CFG["estimators"]["primary"]["spec"],
         "phase_d_registered": CFG["estimators"]["comparator_phase_d_registered"]["spec"]}


def ld(p):
    return json.loads(Path(p).read_text())


def fil(t):
    return t.split("::", 1)[0]


def r4(x):
    return None if x is None else round(float(x), 4)


def fs(xs):
    return math.fsum(sorted(xs))


def q7(xs, q):
    s = sorted(xs)
    h = (len(s) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (h - lo)


def dur(rec):
    return T if rec["outcome"] == "timeout" else float(rec["duration"])


def stat(xs, s):
    if s["stat"] == "mean":
        return fs(xs) / len(xs)
    if s["stat"] == "median":
        return statistics.median(xs)
    if s["stat"] == "quantile":
        return q7(xs, float(s["q"]))
    raise ValueError(s)


def price(suite, pd, spec):
    files = collections.defaultdict(list)
    for t, d in pd.items():
        files[fil(t)].append(d)
    newp = stat(list(pd.values()), spec["new_file"])
    est, src = {}, {}
    for t in suite:
        if t in pd:
            est[t], src[t] = pd[t], "seen"
        elif len(files.get(fil(t), [])) >= int(spec["min_seen"]):
            est[t], src[t] = stat(files[fil(t)], spec["in_file"]), "in_file"
        else:
            est[t], src[t] = newp, "new_file"
    return est, src, newp


def cheapest(suite, c, b):
    pos = {t: i for i, t in enumerate(suite)}
    out, s = [], 0.0
    for t in sorted(suite, key=lambda t: (c[t], pos[t])):
        if s + c[t] <= b:
            out.append(t)
            s += c[t]
    return out


def coast(suite, c, b):
    pos = {t: i for i, t in enumerate(suite)}
    cov, out, rest, s = set(), [], [], 0.0
    for t in sorted(suite, key=lambda t: (c[t], pos[t])):
        if fil(t) in cov:
            rest.append(t)
        elif s + c[t] <= b:
            out.append(t)
            s += c[t]
            cov.add(fil(t))
    for t in rest:
        if s + c[t] <= b:
            out.append(t)
            s += c[t]
    return out


PLAN = {"cheapest_first": cheapest, "coast_d": coast}


def phases(v, k):
    ph = {}
    for p in sorted(glob.glob(str(RUNS / f"w{v}_t{v}" / f"pass{k}" / "files" / "*.jsonl"))):
        for line in open(p):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("ev") == "done":
                ph[r["id"]] = (r.get("setup") or 0.0, r.get("call") or 0.0, r.get("teardown") or 0.0)
    return ph


def load(e):
    P, B = e["P"], e["B"]
    suite = list(dict.fromkeys(ld(A / f"collect_{B}.json")["collected"]))
    pd = {t: dur(r) for t, r in ld(A / f"run_w{P}_t{P}_pass1.json")["tests"].items()}
    passes = [{t: dur(r) for t, r in ld(A / f"run_w{B}_t{B}_pass{k}.json")["tests"].items()} for k in (1, 2)]
    real = {t: fs([p[t] for p in passes if t in p]) / sum(1 for p in passes if t in p) for t in suite}
    return suite, pd, passes, real


def spend_split(suite, est, src, real, b, plan):
    g = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for t in plan:
        x = g[src[t]]
        x[0] += 1
        x[1] += est[t]
        x[2] += real[t]
    return {"spend_ratio": r4(fs(real[t] for t in plan) / b),
            "by_source": {s: {"n_selected": g[s][0], "est_over_budget": r4(g[s][1] / b), "real_over_budget": r4(g[s][2] / b),
                              "real_over_est": r4(g[s][2] / g[s][1]) if g[s][1] else None}
                          for s in ("seen", "in_file", "new_file")}}


def pair_diag(e):
    suite, pd, passes, real = load(e)
    est, src, newp = price(suite, pd, SPECS["primary"])
    estd, srcd, newpd = price(suite, pd, SPECS["phase_d_registered"])
    te, ted, tr = fs(est.values()), fs(estd.values()), fs(real.values())
    conf = next(p for p in CONF["pairs"] if p["event_id"] == e["event_id"])
    out = {"event_id": e["event_id"], "P": e["P"], "B": e["B"], "kind": e.get("kind"), "suite_size": len(suite),
           "source_counts": {s: sum(1 for t in suite if src[t] == s) for s in ("seen", "in_file", "new_file")},
           "suite_cost": {"total_est_s": r4(te), "total_real_s": r4(tr), "rel_error": r4(te / tr - 1),
                          "seen_est_s": r4(fs(est[t] for t in suite if src[t] == "seen")),
                          "seen_real_s": r4(fs(real[t] for t in suite if src[t] == "seen")),
                          "in_file_est_s": r4(fs(est[t] for t in suite if src[t] == "in_file")),
                          "in_file_real_s": r4(fs(real[t] for t in suite if src[t] == "in_file")),
                          "new_file_est_s": r4(fs(est[t] for t in suite if src[t] == "new_file")),
                          "new_file_real_s": r4(fs(real[t] for t in suite if src[t] == "new_file"))},
           "new_file_price_primary_P99_s": r4(newp), "new_file_price_phase_d_median_s": r4(newpd),
           "spend_split_primary": {}, "new_file_coverage": {}, "primary_vs_phase_d_rule": {}, "consistency": {}}
    # new files (files with < min_seen seen tests; here: files absent from P)
    nf = collections.defaultdict(list)
    for t in suite:
        if src[t] == "new_file":
            nf[fil(t)].append(t)
    out["new_files"] = [{"file": f, "n_tests": len(ts), "est_each_s": r4(est[ts[0]]), "est_s": r4(fs(est[t] for t in ts)),
                         "real_s": r4(fs(real[t] for t in ts)), "real_median_s": r4(statistics.median(real[t] for t in ts)),
                         "real_max_s": r4(max(real[t] for t in ts)),
                         "share_tests_real_above_price": r4(sum(real[t] > est[t] for t in ts) / len(ts))}
                        for f, ts in sorted(nf.items())]
    n_new = sum(len(v) for v in nf.values())
    for f in FR:
        b = f * te
        bd = f * ted
        for pol in POL:
            plan = PLAN[pol](suite, est, b)
            pland = PLAN[pol](suite, estd, bd)
            sp = spend_split(suite, est, src, real, b, plan)
            out["spend_split_primary"][f"{pol}@{f}"] = sp
            ref = conf["estimators"]["primary"]["tiers"][str(f)][pol]["spend_ratio"]
            out["consistency"][f"{pol}@{f}"] = abs(ref - fs(real[t] for t in plan) / b) < 5e-6
            sel_new = [t for t in plan if src[t] == "new_file"]
            sel_new_d = [t for t in pland if srcd[t] == "new_file"]
            out["new_file_coverage"][f"{pol}@{f}"] = {
                "n_new_file_tests": n_new, "selected_primary": len(sel_new),
                "share_primary": r4(len(sel_new) / n_new) if n_new else None,
                "new_files_touched_primary": len({fil(t) for t in sel_new}),
                "selected_phase_d_rule": len(sel_new_d), "share_phase_d_rule": r4(len(sel_new_d) / n_new) if n_new else None}
            rd = fs(real[t] for t in pland) / bd
            out["primary_vs_phase_d_rule"][f"{pol}@{f}"] = {"primary": r4(fs(real[t] for t in plan) / b), "phase_d_rule": r4(rd),
                                                            "phase_d_rule_new_file_real_over_budget": r4(fs(real[t] for t in pland if srcd[t] == "new_file") / bd),
                                                            "phase_d_rule_in_file_real_over_budget": r4(fs(real[t] for t in pland if srcd[t] == "in_file") / bd)}
    # largest single-test excess (real - est) inside the primary cheapest_first plans, and the ratio without it
    tops = {}
    for f in FR:
        b = f * te
        plan = cheapest(suite, est, b)
        srt = sorted(plan, key=lambda t: -(real[t] - est[t]))
        w = srt[0]
        tops[str(f)] = {"worst_test": w, "src": src[w], "est_s": r4(est[w]), "real_s": r4(real[w]),
                        "per_pass_s": [r4(p.get(w)) for p in passes], "real_over_budget": r4(real[w] / b),
                        "spend_ratio": r4(fs(real[t] for t in plan) / b),
                        "spend_ratio_without_worst_test": r4((fs(real[t] for t in plan) - real[w]) / b),
                        "top5_excess_tests": [{"test": t, "src": src[t], "est_s": r4(est[t]), "real_s": r4(real[t])} for t in srt[:5]]}
    out["worst_test_cheapest_first"] = tops
    # outcome change P -> B: a seen test SKIPPED on P is priced at its (near-zero) skip time; if it RUNS on B it is
    # charged its full run time. Contribution of such tests to the cheapest_first spend.
    prec = ld(A / f"run_w{e['P']}_t{e['P']}_pass1.json")["tests"]
    b1 = ld(A / f"run_w{e['B']}_t{e['B']}_pass1.json")["tests"]
    s2r = [t for t in suite if src[t] == "seen" and prec[t]["outcome"] == "skipped" and b1[t]["outcome"] != "skipped"]
    r2s = [t for t in suite if src[t] == "seen" and prec[t]["outcome"] != "skipped" and b1[t]["outcome"] == "skipped"]
    sk = {"n_seen_skipped_on_P_run_on_B": len(s2r), "n_seen_run_on_P_skipped_on_B": len(r2s),
          "skipped_to_run_tests": [{"test": t, "est_s": r4(est[t]), "real_s": r4(real[t]), "B_outcome": b1[t]["outcome"]} for t in s2r][:10]}
    for f in FR:
        b = f * te
        for pol in POL:
            plan = PLAN[pol](suite, est, b)
            ps = set(plan)
            sel = [t for t in s2r if t in ps]
            sk[f"{pol}@{f}"] = {"selected_skipped_to_run": len(sel), "their_real_over_budget": r4(fs(real[t] for t in sel) / b),
                                "spend_ratio_without_them": r4((fs(real[t] for t in plan) - fs(real[t] for t in sel)) / b)}
    out["outcome_change_seen"] = sk
    # winner's curse: seen tests in the 5% plan vs the rest; within-B self-selection (pass1 -> pass2)
    b5 = 0.05 * te
    plan5 = set(cheapest(suite, est, b5))
    seen = [t for t in suite if src[t] == "seen"]
    sel = [t for t in seen if t in plan5]
    non = [t for t in seen if t not in plan5]
    p1, p2 = passes
    tot1 = fs(p1[t] for t in suite)
    pl = cheapest(suite, p1, 0.05 * tot1)
    out["seen_drift"] = {"seen_selected_5pct_real_over_est": r4(fs(real[t] for t in sel) / fs(est[t] for t in sel)),
                         "seen_not_selected_real_over_est": r4(fs(real[t] for t in non) / fs(est[t] for t in non)) if non else None,
                         "seen_selected_5pct_median_per_test_real_over_est": r4(statistics.median(real[t] / est[t] for t in sel if est[t] > 0)),
                         "seen_selected_5pct_median_real_minus_est_ms": r4(1000 * statistics.median(real[t] - est[t] for t in sel)),
                         "seen_selected_5pct_median_est_ms": r4(1000 * statistics.median(est[t] for t in sel)),
                         "seen_not_selected_median_real_minus_est_ms": r4(1000 * statistics.median(real[t] - est[t] for t in non)) if non else None,
                         "within_B_self_selection_pass1_to_pass2_spend_5pct": r4(fs(p2[t] for t in pl) / (0.05 * tot1))}
    return out, (suite, est, src, real, te)


def e2_detail(ctx, e):
    """Per-file decomposition of E2's 5% / 25% cheapest_first excess and the setup/call/teardown split of the seen
    tests in the 5% plan (P pass 1 vs B pass 1)."""
    suite, est, src, real, te = ctx
    res = {}
    for f in FR:
        b = f * te
        plan = cheapest(suite, est, b)
        g = collections.defaultdict(lambda: [0, 0.0, 0.0, collections.Counter()])
        for t in plan:
            x = g[fil(t)]
            x[0] += 1
            x[1] += est[t]
            x[2] += real[t]
            x[3][src[t]] += 1
        exc = fs(v[2] - v[1] for v in g.values())
        rows = sorted(g.items(), key=lambda kv: -(kv[1][2] - kv[1][1]))
        res[str(f)] = {"budget_s": r4(b), "real_spend_s": r4(fs(real[t] for t in plan)), "excess_s": r4(exc),
                       "top_files_by_excess": [{"file": k, "n_selected": v[0], "est_s": r4(v[1]), "real_s": r4(v[2]),
                                                "excess_s": r4(v[2] - v[1]), "excess_over_budget": r4((v[2] - v[1]) / b),
                                                "sources": dict(v[3])} for k, v in rows[:8]]}
    PP, PB = phases(e["P"], 1), phases(e["B"], 1)
    plan5 = cheapest(suite, est, 0.05 * te)
    s = [t for t in plan5 if src[t] == "seen" and t in PP and t in PB]
    res["seen_in_5pct_plan_phase_split_s"] = {n: {"P": r4(fs(PP[t][i] for t in s)), "B_pass1": r4(fs(PB[t][i] for t in s))}
                                              for i, n in enumerate(("setup", "call", "teardown"))}
    # parametrised siblings of the worst test: is the slowdown one case or the whole family?
    w = max(plan5, key=lambda t: real[t] - est[t])
    fam = w.rsplit("_", 2)[0]
    res["worst_test_family"] = {"prefix": fam, "members": [{"test": t.split("::")[-1], "in_5pct_plan": t in set(plan5),
                                                             "est_s": r4(est[t]), "real_s": r4(real[t])}
                                                            for t in suite if t.startswith(fam)]}
    return res


def main():
    pairs, ctxs = [], {}
    for e in PAIRS:
        d, ctx = pair_diag(e)
        pairs.append(d)
        ctxs[e["event_id"]] = (ctx, e)
    n_with_new = [p["event_id"] for p in pairs if p["source_counts"]["new_file"]]
    summary = {
        "pairs_with_brand_new_files": n_with_new,
        "n_pairs_with_brand_new_files": len(n_with_new),
        "new_file_tests_total": sum(p["source_counts"]["new_file"] for p in pairs),
        "new_files_total": sum(len(p["new_files"]) for p in pairs),
        "spend_ratio_seen_part_vs_unseen_part": {p["event_id"]: {k: {"seen": v["by_source"]["seen"]["real_over_budget"],
                                                                   "in_file": v["by_source"]["in_file"]["real_over_budget"],
                                                                   "new_file": v["by_source"]["new_file"]["real_over_budget"]}
                                                               for k, v in p["spend_split_primary"].items()} for p in pairs},
        "primary_vs_phase_d_rule": {p["event_id"]: p["primary_vs_phase_d_rule"] for p in pairs},
        "skipped_on_P_run_on_B": {p["event_id"]: {"n": p["outcome_change_seen"]["n_seen_skipped_on_P_run_on_B"],
                                                  **{k: v for k, v in p["outcome_change_seen"].items() if "@" in k}} for p in pairs},
        "all_consistent_with_confirmatory": all(all(p["consistency"].values()) for p in pairs),
    }
    out = {"schema": "phase_e_exploratory_diagnostics/1",
           "label": "POST HOC / EXPLORATORY. Written after the confirmatory run. No confirmatory claim.",
           "summary": summary, "E2_detail": e2_detail(*ctxs["E2"]), "pairs": pairs}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=False))
    print(json.dumps({"wrote": str(OUT), "consistent": summary["all_consistent_with_confirmatory"],
                      "pairs_with_new_files": n_with_new}))


if __name__ == "__main__":
    main()
