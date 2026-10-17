"""Pre-registration-time prior-predictive check of Phase D (adversarial review, 2026-10-18). NOT study data.

Question: given only what was observed BEFORE the record (2.2.2 file-level pytest times and test counts, the pilot's
number of failing ddt cases per event, D7's hang, the 2.3.1 dry-run per-test durations showing sub-millisecond tests),
are the confirmatory outcomes near-certain by construction? A synthetic suite is built per event from the 2.2.2
file-level times (per-file test time = pytest-reported time minus 0.27 s collection overhead, spread over the file's
tests with a log-normal within-file shape), P costs = real costs x log-normal noise x a release drift factor, and the
registered analysis functions (coast_d, time box, APFDc, Wilcoxon, decision rules) are applied. The proxy ignores
that 2.4/2.5 suites are about 3x larger and that file positions differ by release; it is a plausibility check, not a
forecast of values. Output: phase_d/review_2026-10-18/prior_predictive.json.

    python phase_d/review_2026-10-18/prior_predictive.py [n_sims]
"""
import importlib.util
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pda", REPO / "phase_d/analysis/phase_d_analysis.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

OBS = REPO / "phase_d/sandbox_helpers_2026-10-18/prior_observations/slice_qiskit_2.2.2_filelevel.txt"
# event -> (logical file stem, failing ddt cases in the pilot, position rule, fixed real cost or None)
EVENTS = {"D1": ("compiler/test_transpiler.py", 2, "class", None), "D2": ("test_preset_passmanagers.py", 1, "end", None),
          "D3": ("test_preset_passmanagers.py", 8, "class", None), "D4": ("test_commutative_cancellation.py", 2, "class", None),
          "D5": ("test_clifford_t_passmanager.py", 3, "class", None), "D6": ("test_vf2_layout.py", 2, "class", None),
          "D7": ("test_optimize_1q_decomposition.py", 1, "class", 60.0), "D8": ("test_elide_permutations.py", 1, "class", None)}


def files():
    rows = []
    for ln in OBS.read_text().splitlines():
        if "|" not in ln:
            continue
        f, _, res = [x.strip() for x in ln.split("|")]
        m = re.search(r"in ([\d.]+)s", res)
        n = sum(int(a) for a, _ in re.findall(r"(\d+) (passed|skipped|failed)", res))
        if n and "unitary_synthesis_plugin" not in f:
            rows.append((f, n, max(float(m.group(1)) - 0.27, 0.0005 * n)))
    return rows


def one_sim(rng, rows, sw, end_rule=False):
    res = {}
    for eid, (stem, k, rule, fixed) in EVENTS.items():
        suite, real = [], {}
        for f, n, S in rows:
            w = [math.exp(rng.gauss(0, sw)) for _ in range(n)]
            sc = S / sum(w)
            for j in range(n):
                t = f"{f}::C::t{j:04d}"
                suite.append(t)
                real[t] = w[j] * sc
        drift = math.exp(rng.gauss(0, 0.15))
        pdur = {t: real[t] * drift * math.exp(rng.gauss(0, 0.3)) for t in suite}
        lf = next(f for f, _, _ in rows if f.endswith(stem))
        ftests = [t for t in suite if t.startswith(lf + "::")]
        pos = len(ftests) if (rule == "end" or end_rule) else rng.randint(0, len(ftests))
        fmed = statistics.median(sorted(real[t] for t in ftests))
        bps = [f"{lf}::C::zbp{i}" for i in range(k)]
        for b in bps:
            real[b] = fixed if fixed else fmed * math.exp(rng.gauss(1.0, 1.5))
        i0 = suite.index(ftests[0]) + pos
        suite = suite[:i0] + bps + suite[i0:]
        est, _ = A.estimator(suite, pdur, 3, 1.0)
        D = set(bps)
        tot = A.fsum_sorted(est.values())
        r = {"apfdc": {"default": A.apfdc(suite, real, D), "coast_d": A.apfdc(A.coast_d(suite, est), real, D),
                       "cheapest_first": A.apfdc(A.order_cheapest(suite, est), real, D)}}
        rnd = [A.order_random(suite, s) for s in range(20)]
        r["apfdc"]["random"] = statistics.mean(A.apfdc(o, real, D) for o in rnd)
        pre = [t for t in suite if t not in D]
        r["p2"] = A.fsum_sorted(est[t] for t in pre) / A.fsum_sorted(real[t] for t in pre) - 1
        r["tiers"] = {}
        for f in (0.05, 0.25):
            b = f * tot
            plan = A.coast_d(suite, est, b)
            planc = A.plan_greedy(A.order_cheapest(suite, est), est, b)
            r["tiers"][f] = {
                "coast_d": int(bool(set(A.time_box(plan, real, b)) & D)),
                "default": int(bool(set(A.time_box(suite, real, b)) & D)),
                "file_rr": int(bool(set(A.time_box(A.order_file_rr(suite), real, b)) & D)),
                "random": statistics.mean(int(bool(set(A.time_box(o, real, b)) & D)) for o in rnd),
                "spend_coast_pre": A.fsum_sorted(real[t] for t in plan if t not in D) / b,
                "spend_cheap_pre": A.fsum_sorted(real[t] for t in planc if t not in D) / b,
                "spend_coast_all": A.fsum_sorted(real[t] for t in plan) / b}
        res[eid] = r
    return res


def decide(res):
    out = {}
    for h, (a, b) in {"H1": ("coast_d", "default"), "H2": ("coast_d", "random")}.items():
        d = [A.r6(res[e]["apfdc"][a] - res[e]["apfdc"][b]) for e in sorted(res)]
        out[h] = {"p": A.wilcoxon_exact_greater(d)["p"], "mean": sum(d) / len(d), "wins": sum(x > 0 for x in d)}
    out["H1_alone_supported"] = out["H1"]["p"] < 0.05 and out["H1"]["mean"] > 0
    hh = A.holm({"H1": out["H1"]["p"], "H2": out["H2"]["p"]}, 0.05)
    out["H1_holm"] = hh["H1"]["reject"] and out["H1"]["mean"] > 0
    out["H2_holm"] = hh["H2"]["reject"] and out["H2"]["mean"] > 0
    d1 = []
    for f in (0.05, 0.25):
        c = {p: sum(res[e]["tiers"][f][p] for e in res) for p in ("coast_d", "default", "file_rr", "random")}
        d1.append((c["coast_d"] >= c["default"] and c["coast_d"] >= c["file_rr"] and c["coast_d"] >= c["random"] - 1e-9,
                   c["coast_d"] > c["default"], c))
    out["D1"] = all(x[0] for x in d1) and any(x[1] for x in d1)
    out["D1_counts"] = {str(f): x[2] for f, x in zip((0.05, 0.25), d1)}
    for key in ("spend_coast_pre", "spend_cheap_pre", "spend_coast_all"):
        ok = True
        for f in (0.05, 0.25):
            xs = [res[e]["tiers"][f][key] for e in res]
            ok = ok and (sum(xs) / len(xs) <= 1.25 and max(xs) <= 2.0)
        out["P1_" + key] = ok
    out["P2"] = all(abs(res[e]["p2"]) <= 0.25 for e in res)
    out["coast_le_cheapest_all_events"] = all(res[e]["apfdc"]["coast_d"] <= res[e]["apfdc"]["cheapest_first"] + 1e-12 for e in res)
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rows = files()
    summary = {}
    for sw in (1.0, 1.5, 2.0):
        for end_rule in (False, True):
            rng = random.Random(20261018)
            ds = [decide(one_sim(rng, rows, sw, end_rule)) for _ in range(n)]
            key = f"sigma_within={sw},backport_position={'end_of_file' if end_rule else 'class_alphabetical'}"
            summary[key] = {k: sum(1 for d in ds if d[k]) / n for k in
                            ("H1_alone_supported", "H1_holm", "H2_holm", "D1", "P1_spend_coast_pre", "P1_spend_cheap_pre",
                             "P1_spend_coast_all", "P2", "coast_le_cheapest_all_events")}
            summary[key]["median_H1_wins_of_8"] = statistics.median(d["H1"]["wins"] for d in ds)
            summary[key]["median_H2_wins_of_8"] = statistics.median(d["H2"]["wins"] for d in ds)
            summary[key]["mean_D1_counts"] = {f: {p: round(statistics.mean(d["D1_counts"][f][p] for d in ds), 2)
                                                  for p in ("coast_d", "default", "file_rr", "random")} for f in ("0.05", "0.25")}
            print(key, json.dumps(summary[key]), flush=True)
    out = {"n_sims_per_setting": n, "note": __doc__.split("\n\n")[0], "summary": summary}
    (Path(__file__).parent / "prior_predictive.json").write_text(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
