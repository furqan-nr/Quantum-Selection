"""Independent verification of the Phase E confirmatory result (PREREGISTRATION_PHASE_E.md).

Does NOT import phase_e/analysis/phase_e_analysis.py. Re-implements, from the pre-registration text and the frozen
config, the new-test-aware estimators, the budgets, the two cost-aware plans (cheapest_first, coast_d), the spend
ratios, P1', P2' and the Phase-D-rule comparator, and compares every number with results/phase_e_confirmatory.json.
Also performs the integrity, timeline and completeness checks (Part 1, items 1-3 of the verification brief).

Read-only. Standard library only. Deterministic.

    python verification/phase_e_recompute.py            # prints a JSON report; exit code 0 iff every check passes
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
D = R / "phase_e/data"
A = D / "assembled"
CFG = json.loads((R / "phase_e/config/phase_e_config.json").read_text())
PAIRS = json.loads((R / "phase_e/events/phase_e_pairs.json").read_text())["events"]
RES = json.loads((R / "results/phase_e_confirmatory.json").read_text())
T = float(CFG["runner"]["per_test_timeout_s"])
FRACS = (0.05, 0.25)
TOL = 5e-6  # results file rounds to 6 decimals

# Timeline anchors (GitHub API, furqan-nr/Quantum-Selection): commit time of the pre-registration and of the lock push.
PREREG_COMMIT_UTC = "2026-10-18T21:59:09Z"   # dfc413ce84b6ef67c1ad7e5849117ed5bb3d5e31
LOCK_COMMIT_UTC = "2026-10-18T22:59:42Z"     # 8e81ea858458a4c04b265f201c642e504a2e7c32

checks: list[dict] = []


def check(name, ok, **ev):
    checks.append({"check": name, "pass": bool(ok), **ev})
    return ok


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ld(p):
    return json.loads(Path(p).read_text())


def fsum(xs):
    return math.fsum(sorted(xs))


def fil(t):
    return t.split("::", 1)[0]


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def q7(xs, q):
    s = sorted(xs)
    h = (len(s) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (h - lo)


# ------------------------------------------------------------------------------------------------ 1. integrity
def integrity():
    bad = []
    n = 0
    for line in (R / "PREREGISTRATION_PHASE_E.sha256").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        h, p = line.split(None, 1)
        n += 1
        if sha(R / p.strip()) != h:
            bad.append(p.strip())
    check("manifest_sha256", not bad, n_files=n, mismatches=bad)
    frozen = {l.split()[1]: l.split()[0] for l in (R / "PREREGISTRATION_PHASE_E.sha256").read_text().splitlines()
              if l and not l.startswith("#")}
    fa, fc = frozen["phase_e/analysis/phase_e_analysis.py"], frozen["phase_e/config/phase_e_config.json"]
    check("results_analysis_and_config_hash_equal_frozen", RES["analysis_sha256"] == fa and RES["config_sha256"] == fc,
          analysis=RES["analysis_sha256"], config=RES["config_sha256"])
    lp = ld(D / "budget_lock/LOCK_PUSHED.json")
    mism = {k: (sha(D / "budget_lock" / k), v) for k, v in lp["lock_sha256"].items() if sha(D / "budget_lock" / k) != v}
    locks_ok = all(ld(D / "budget_lock" / f"{e['event_id']}.json")["analysis_sha256"] == fa
                   and ld(D / "budget_lock" / f"{e['event_id']}.json")["config_sha256"] == fc for e in PAIRS)
    check("locks_match_LOCK_PUSHED", not mism and len(lp["lock_sha256"]) == 10, commit=lp["commit"], mismatches=mism)
    check("locks_written_by_frozen_analysis_and_config", locks_ok)
    # inputs hashed in the results file == current assembled files; locks reference the current P run / B collect
    inp = {p.name: sha(p) for p in sorted(A.glob("*.json"))}
    check("results_inputs_sha256_equal_assembled", inp == RES["inputs_sha256"], n_inputs=len(inp))
    lk_bad = []
    for e in PAIRS:
        lk = ld(D / "budget_lock" / f"{e['event_id']}.json")
        if lk["p_run_sha256"] != sha(A / f"run_w{e['P']}_t{e['P']}_pass1.json") or lk["b_collect_sha256"] != sha(A / f"collect_{e['B']}.json"):
            lk_bad.append(e["event_id"])
    check("locks_reference_current_P_run_and_B_collect", not lk_bad, mismatches=lk_bad)


# ------------------------------------------------------------------------------------------------ 2. timeline
def raw_times(d):
    """earliest / latest timestamp in a raw run directory: per-test jsonl 't' fields, env call records, file mtimes."""
    ts = []
    for f in glob.glob(str(d / "files/*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "t" in r:
                ts.append(float(r["t"]))
    env = [ld(f)["utc"] for f in glob.glob(str(d / "env/*.json"))]
    mt = [Path(f).stat().st_mtime for f in glob.glob(str(d / "**/*"), recursive=True) if Path(f).is_file()]
    return {"first_record": iso(min(ts)) if ts else None, "last_record": iso(max(ts)) if ts else None,
            "first_env_call": min(env) if env else None, "last_file_mtime": iso(max(mt)) if mt else None,
            "first_file_mtime": iso(min(mt)) if mt else None}


def timeline():
    locks = {e["event_id"]: ld(D / "budget_lock" / f"{e['event_id']}.json")["locked_utc"] for e in PAIRS}
    first_lock = min(locks.values())
    lock_mtimes = [iso((D / "budget_lock" / f"{e['event_id']}.json").stat().st_mtime) for e in PAIRS]
    b_rows, p_rows, c_rows = {}, {}, {}
    all_first = []
    for e in PAIRS:
        P, B = e["P"], e["B"]
        bt = {k: raw_times(D / f"runs/w{B}_t{B}/pass{k}") for k in (1, 2)}
        b_rows[f"{e['event_id']} {B}"] = {"earliest_B_record": min(v["first_record"] for v in bt.values()),
                                           "earliest_B_file_mtime": min(v["first_file_mtime"] for v in bt.values())}
        pt = raw_times(D / f"runs/w{P}_t{P}/pass1")
        p_rows[f"{e['event_id']} {P}"] = {"first": pt["first_record"], "last_record": pt["last_record"],
                                           "last_file_mtime": pt["last_file_mtime"]}
        cdir = D / f"collect/{B}"
        cm = [Path(f).stat().st_mtime for f in glob.glob(str(cdir / "*"))]
        c_rows[f"{e['event_id']} {B}"] = {"complete_utc": ld(cdir / "COMPLETE.json")["utc"],
                                          "first_mtime": iso(min(cm)), "last_mtime": iso(max(cm))}
        all_first += [pt["first_record"], pt["first_file_mtime"], iso(min(cm))]
    earliest_B = min(v["earliest_B_record"] for v in b_rows.values())
    earliest_B_mt = min(v["earliest_B_file_mtime"] for v in b_rows.values())
    check("every_B_record_after_lock_commit", earliest_B > LOCK_COMMIT_UTC and earliest_B_mt > LOCK_COMMIT_UTC,
          lock_commit=LOCK_COMMIT_UTC, earliest_B_record=earliest_B, earliest_B_file_mtime=earliest_B_mt, per_release=b_rows)
    last_p = max(max(v["last_record"], v["last_file_mtime"]) for v in p_rows.values())
    last_c = max(v["last_mtime"] for v in c_rows.values())
    check("all_P_runs_and_B_collects_precede_lock_writing", last_p < first_lock and last_c < first_lock,
          first_lock_written=first_lock, lock_file_mtimes=[min(lock_mtimes), max(lock_mtimes)],
          last_P_activity=last_p, last_collect_activity=last_c, P_runs=p_rows, collects=c_rows)
    earliest = min(all_first)
    check("no_study_measurement_before_prereg_commit", earliest > PREREG_COMMIT_UTC, prereg_commit=PREREG_COMMIT_UTC,
          earliest_study_data=earliest,
          note="pre-registration-time contact with the fresh releases is limited to PyPI metadata, sdist member names and "
               "a pip dry-run resolution (release_checks.json, checked_utc " + ld(R / "phase_e/tools/release_checks.json")["checked_utc"]
               + "), disclosed in Section 10; dry run used 2.2.3 (a Phase D release)")
    dr = json.dumps(ld(R / "phase_e/dryrun/dryrun_config.json"))
    fresh = {v for e in PAIRS for v in (e["P"], e["B"])}
    check("dryrun_uses_no_phase_e_release", not any(f'"{v}"' in dr for v in fresh))


# ------------------------------------------------------------------------------------------------ 3. completeness
def completeness():
    rows, ok = {}, True
    for e in PAIRS:
        P, B = e["P"], e["B"]
        col = ld(A / f"collect_{B}.json")["collected"]
        suite = list(dict.fromkeys(col))
        pr = ld(A / f"run_w{P}_t{P}_pass1.json")
        oc_all = []
        row = {"suite": len(suite), "collect_duplicates": len(col) - len(suite), "P_complete": pr.get("complete"),
               "P_tests": len(pr["tests"])}
        for k in (1, 2):
            br = ld(A / f"run_w{B}_t{B}_pass{k}.json")
            ids = set(br["tests"])
            row[f"B{k}_complete"] = br.get("complete")
            row[f"B{k}_equals_collect"] = ids == set(suite)
            row[f"B{k}_missing"] = len(set(suite) - ids)
            row[f"B{k}_extra"] = len(ids - set(suite))
            oc = {}
            for t in suite:
                if t in br["tests"]:
                    o = br["tests"][t]["outcome"]
                    oc[o] = oc.get(o, 0) + 1
            row[f"B{k}_outcomes"] = dict(sorted(oc.items()))
            oc_all.append(oc)
            ok &= bool(br.get("complete")) and ids == set(suite)
        # raw COMPLETE markers
        row["raw_COMPLETE_markers"] = all((D / f"runs/w{B}_t{B}/pass{k}/COMPLETE.json").exists() for k in (1, 2)) and \
            (D / f"runs/w{P}_t{P}/pass1/COMPLETE.json").exists() and (D / f"collect/{B}/COMPLETE.json").exists()
        row["matches_results_outcome_counts"] = oc_all[0] == next(p for p in RES["pairs"] if p["event_id"] == e["event_id"])["outcome_counts_B_pass1"]
        ok &= bool(pr.get("complete")) and row["raw_COMPLETE_markers"] and row["matches_results_outcome_counts"]
        rows[e["event_id"]] = row
    check("completeness_all_runs_complete_B_equals_collect", ok, per_pair=rows,
          deviations_in_results=RES["deviations"], excluded=RES["excluded_pairs"])


# ------------------------------------------------------------------------------------------------ 5. recomputation
def prices(suite, pdur, spec):
    files = {}
    for t, d in pdur.items():
        files.setdefault(fil(t), []).append(d)
    alld = list(pdur.values())

    def st(xs, s):
        if s["stat"] == "mean":
            return fsum(xs) / len(xs)
        if s["stat"] == "median":
            return statistics.median(xs)
        if s["stat"] == "quantile":
            return q7(xs, float(s["q"]))
        raise ValueError(s)
    newp = st(alld, spec["new_file"])
    est, src = {}, {}
    for t in suite:
        if t in pdur:
            est[t], src[t] = pdur[t], "seen"
        elif len(files.get(fil(t), [])) >= int(spec["min_seen"]):
            est[t], src[t] = st(files[fil(t)], spec["in_file"]), "in_file"
        else:
            est[t], src[t] = newp, "new_file"
    return est, src


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
    covered, out, rest, s = set(), [], [], 0.0
    for t in sorted(suite, key=lambda t: (c[t], pos[t])):
        if fil(t) in covered:
            rest.append(t)
        elif s + c[t] <= b:
            out.append(t)
            s += c[t]
            covered.add(fil(t))
    for t in rest:
        if s + c[t] <= b:
            out.append(t)
            s += c[t]
    return out


def pair_data(e):
    P, B = e["P"], e["B"]
    suite = list(dict.fromkeys(ld(A / f"collect_{B}.json")["collected"]))
    pdur = {t: (T if r["outcome"] == "timeout" else float(r["duration"])) for t, r in ld(A / f"run_w{P}_t{P}_pass1.json")["tests"].items()}
    passes = [{t: (T if r["outcome"] == "timeout" else float(r["duration"])) for t, r in ld(A / f"run_w{B}_t{B}_pass{k}.json")["tests"].items()}
              for k in (1, 2)]
    real = {t: fsum([p[t] for p in passes if t in p]) / sum(1 for p in passes if t in p) for t in suite}
    # speed rule
    cp = statistics.median(x["calibration_median_s"] for x in ld(A / f"run_w{P}_t{P}_pass1.json")["env"])
    cb = ld(A / f"collect_{B}.json")["meta"]["calibration_median_s"]
    k = cb / cp
    lo, hi = CFG["estimator_common"]["speed_band"]
    kap = k if (k < lo or k > hi) else 1.0
    return suite, pdur, real, kap, k


def recompute():
    specs = {"primary": CFG["estimators"]["primary"]["spec"], "secondary": CFG["estimators"]["secondary"]["spec"],
             "phase_d_registered": CFG["estimators"]["comparator_phase_d_registered"]["spec"]}
    mine = {n: {"ratios": {}, "err": {}} for n in specs}
    diffs = []
    for e in PAIRS:
        suite, pdur, real, kap, k = pair_data(e)
        rp = next(p for p in RES["pairs"] if p["event_id"] == e["event_id"])
        if abs(rp["speed"]["k_measured"] - k) > 1e-9 or rp["speed"]["k_applied"] != kap:
            diffs.append((e["event_id"], "speed"))
        for n, spec in specs.items():
            est, src = prices(suite, pdur, spec)
            est = {t: v * kap for t, v in est.items()}
            te, tr = fsum(est.values()), fsum(real.values())
            err = te / tr - 1
            mine[n]["err"][e["event_id"]] = err
            ref = rp["estimators"][n]
            if abs(ref["suite_cost_rel_error"] - err) > TOL:
                diffs.append((e["event_id"], n, "err", ref["suite_cost_rel_error"], err))
            lk = ld(D / "budget_lock" / f"{e['event_id']}.json")["estimators"][n]
            for f in FRACS:
                b = f * te
                if abs(lk["budgets_s"][str(f)] - b) > TOL:
                    diffs.append((e["event_id"], n, f, "budget_vs_lock", lk["budgets_s"][str(f)], b))
                for pol, plan in (("cheapest_first", cheapest(suite, est, b)), ("coast_d", coast(suite, est, b))):
                    ratio = fsum(real[t] for t in plan) / b
                    mine[n]["ratios"].setdefault(f"{pol}@{f}", []).append(ratio)
                    rr = ref["tiers"][str(f)][pol]
                    if abs(rr["spend_ratio"] - ratio) > TOL or rr["selected"] != len(plan):
                        diffs.append((e["event_id"], n, pol, f, rr["spend_ratio"], ratio))
    out = {}
    for n in specs:
        crit = {c: {"mean": fsum(v) / len(v), "max": max(v), "per_pair": [round(x, 6) for x in v],
                    "holds_P1prime": max(v) <= 1.25} for c, v in mine[n]["ratios"].items()}
        a = sorted(abs(x) for x in mine[n]["err"].values())
        med, share = statistics.median(a), sum(x <= 0.25 for x in a) / len(a)
        out[n] = {"P1prime": all(c["holds_P1prime"] for c in crit.values()), "criteria": crit,
                  "P2prime": med <= 0.15 and share >= 0.8, "median_abs_err": med, "share_within_25": share,
                  "continuity_P1_phaseD": all(c["mean"] <= 1.25 and c["max"] <= 2.0 for c in crit.values())}
        dec = RES["decisions"][n]
        if out[n]["P1prime"] != dec["P1prime"]["supported"] or out[n]["P2prime"] != dec["P2prime"]["supported"]:
            diffs.append((n, "decision"))
    check("independent_recompute_matches_results", not diffs, n_differences=len(diffs), differences=diffs[:20])
    check("P1prime_not_supported_P2prime_supported", (not out["primary"]["P1prime"]) and out["primary"]["P2prime"],
          primary=out["primary"])
    return out


def main():
    integrity()
    timeline()
    completeness()
    rec = recompute()
    rep = {"all_pass": all(c["pass"] for c in checks), "checks": checks,
           "comparator_phase_d_registered": rec["phase_d_registered"], "secondary": rec["secondary"]}
    print(json.dumps(rep, indent=1, default=str))
    sys.exit(0 if rep["all_pass"] else 1)


if __name__ == "__main__":
    main()
