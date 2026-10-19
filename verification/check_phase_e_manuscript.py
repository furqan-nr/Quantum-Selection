"""Check every Phase E (RQ8) number used in the manuscript against the frozen sources.

Sources: results/phase_e_confirmatory.json, results/phase_e_exploratory_diagnostics.json,
phase_e/dev/estimator_selection.json, phase_e/events/phase_e_pairs.json, phase_e/data/budget_lock/*.json
(+ LOCK_PUSHED.json), phase_e/data/runs/*/pass*/files/*.jsonl (earliest B record), and
verification/phase_e_independent_check.md (GitHub commit times).
Each expected string is computed from the sources (never typed as a number) and must occur in the named file.
Also checks: decisions, OR1 Section S6 equals its generator output, abstract <= 250 words, no em-dash and no
sentence-joining semicolon in the RQ8 section, and the cover letter figures.
Usage: python verification/check_phase_e_manuscript.py   (exit 1 on any failure)
"""
import datetime as dt
import glob
import json
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "results/phase_e_confirmatory.json").read_text())
X = json.loads((ROOT / "results/phase_e_exploratory_diagnostics.json").read_text())
S = json.loads((ROOT / "phase_e/dev/estimator_selection.json").read_text())
LEDGER = json.loads((ROOT / "phase_e/events/phase_e_pairs.json").read_text())["events"]
PUSH = json.loads((ROOT / "phase_e/data/budget_lock/LOCK_PUSHED.json").read_text())
CHECK = (ROOT / "verification/phase_e_independent_check.md").read_text()
MAIN = (ROOT / "paper/sqj/main.tex").read_text()
OR1 = (ROOT / "paper/sqj/or1_phasee.tex").read_text()
COVER = (ROOT / "paper/build_cover_letter_sqj.js").read_text()
P = {p["event_id"]: p for p in R["pairs"]}
XP = {p["event_id"]: p for p in X["pairs"]}
IDS = [f"E{i}" for i in range(1, 11)]
D = R["decisions"]
fails, n = [], 0


def need(s, where=MAIN, label=""):
    global n
    n += 1
    if s not in where:
        fails.append(f"missing: {label or s!r}")


def true(cond, label):
    global n
    n += 1
    if not cond:
        fails.append(label)


def f2(x):
    return f"{x:.2f}"


def pctm(x):
    return ("$+" if x >= 0 else "$-") + f"{abs(100 * x):.1f}\\%$"


# ---- integrity of inputs
true([e["event_id"] for e in LEDGER] == IDS and all((e["P"], e["B"]) == (P[e["event_id"]]["P"], P[e["event_id"]]["B"]) for e in LEDGER),
     "ledger mismatch")
for i in IDS:
    lk = json.loads((ROOT / f"phase_e/data/budget_lock/{i}.json").read_text())
    true(abs(lk["estimators"]["primary"]["budgets_s"]["0.05"] - P[i]["estimators"]["primary"]["budgets_s"]["0.05"]) < 1e-9
         and P[i]["budget_lock_matches"], f"lock mismatch {i}")
true(R["deviations"] == [] and R["excluded_pairs"] == [] and all(P[i]["n_imputed_real"] == 0 for i in IDS), "deviations/exclusions")
true(not D["primary"]["P1prime"]["supported"] and D["primary"]["P2prime"]["supported"], "decisions P1' false / P2' true")
true(D["primary"]["P2_strict_continuity"] and not D["primary"]["P1_continuity_phase_d_thresholds"], "continuity checks")
true(not D["secondary"]["P1prime"]["supported"] and D["secondary"]["P2prime"]["supported"], "secondary decisions")

# ---- commits and timeline
for c, t in [("dfc413c", "21:59:09"), ("8e81ea8", "22:59:42")]:
    true(c in CHECK and t in CHECK, f"commit {c} {t} not in independent check")
    need(f"\\texttt{{{c}}}", MAIN, f"commit {c} in main")
    need(t, MAIN, f"commit time {t} in main")
true(PUSH["commit"].startswith("8e81ea8"), "LOCK_PUSHED commit")
ts = []
for i in IDS:
    v = P[i]["B"]
    for f in glob.glob(str(ROOT / f"phase_e/data/runs/w{v}_t{v}/pass*/files/*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "t" in r:
                ts.append(r["t"])
first_b = dt.datetime.fromtimestamp(min(ts), dt.timezone.utc)
need(first_b.strftime("%H:%M:%S"), MAIN, "earliest B record")
margin = int((first_b - dt.datetime(2026, 10, 18, 22, 59, 42, tzinfo=dt.timezone.utc)).total_seconds())
need(f"by {margin}~s", MAIN, "lock margin in threats")
true(margin > 0, "B timing before lock commit")

# ---- development data and forecast
need("Eleven candidate" if len(S["ranking_lopo"]) == 11 else "XX", MAIN, "number of candidate families")
true(S["ranking_lopo"][0]["family"] == S["primary"]["family"] == "F3_mean_newfile_quantile" and S["primary"]["param"] == "q=0.99", "primary family")
lo = S["families"]["F3_mean_newfile_quantile"]["lopo"]
need(f"at or below {f2(max(lo['P1prime'][c]['max'] for c in lo['P1prime']))} times the budget", MAIN, "LOPO max")
words = {4: "four"}
need(f"on only {words[round(lo['P2prime']['share_within_band'] * 6)]} of the six pairs", MAIN, "LOPO P2' share")
fc = S["forecast"]
need(f"P1$'$ holds at {f2(fc['lopo_pool_smoothed']['P1prime'])} and that P2$'$ holds at {f2(fc['lopo_pool_smoothed']['P2prime'])}", MAIN, "forecast")
true(fc["lopo_pool_smoothed_2tau"]["P1prime"] < 0.5 and fc["extended_pool_smoothed_2tau"]["P1prime"] < 0.5, "forecast 2tau < 0.5")
true(max(fc["lopo_pool"]["P2_strict"], fc["extended_pool"]["P2_strict"], fc["lopo_pool_smoothed"]["P2_strict"]) < 0.1, "strict forecast < 0.1")
need("put it at about 0.9", MAIN, "threats forecast")
true(abs(fc["lopo_pool_smoothed"]["P1prime"] - 0.9) < 0.05, "forecast about 0.9")

# ---- pairs description
kinds = [P[i]["kind"] for i in IDS]
true(kinds.count("patch") == 7 and kinds.count("minor") == 3, "7 patch / 3 minor")
need("Seven are patch steps and three open a new minor series")
true(sum(P[i]["P"].startswith("1.") for i in IDS) == 9, "nine 1.x pairs")
need("Nine pairs come from Qiskit 1.0 to 1.4 and one from 2.4")
need("Nine of RQ8's ten pairs come from the Qiskit 1.x line, only four new test files")
true(X["summary"]["new_files_total"] == 4, "four new files")
nf2 = XP["E2"]["new_files"]
nf5 = XP["E5"]["new_files"]
need(f"E2 ({['one', 'two', 'three'][len(nf2) - 1]} files, {sum(f['n_tests'] for f in nf2)} tests) and E5 "
     f"({['one', 'two', 'three'][len(nf5) - 1]} file, {sum(f['n_tests'] for f in nf5)} tests)", MAIN, "new files E2/E5")
ks = [P[i]["speed"]["k_measured"] for i in IDS]
need(f"$k$ from {min(ks):.2f} to {max(ks):.2f}", MAIN, "k range")

# ---- the RQ8 table
for i in IDS:
    p = P[i]
    e = p["estimators"]["primary"]
    sc = e["source_counts"]
    t = e["tiers"]
    c = p["estimators"]["phase_d_registered"]["tiers"]
    row = (f"{i} & {p['P']} $\\rightarrow$ {p['B']} ({p['kind']}) & {p['suite_size']:,} & {sc['in_file']} / {sc['new_file']} & "
           f"{e['total_est_s']:.1f} & {e['total_real_s']:.1f} & {pctm(e['suite_cost_rel_error'])} & "
           f"{f2(t['0.05']['cheapest_first']['spend_ratio'])} & {f2(t['0.05']['coast_d']['spend_ratio'])} & "
           f"{f2(t['0.25']['cheapest_first']['spend_ratio'])} & {f2(t['0.25']['coast_d']['spend_ratio'])} & "
           f"{f2(c['0.05']['cheapest_first']['spend_ratio'])} & {f2(c['0.25']['cheapest_first']['spend_ratio'])} \\\\")
    need(row, MAIN, f"table row {i}")
cp = D["primary"]["P1prime"]["criteria"]
cd = D["phase_d_registered"]["P1prime"]["criteria"]
pp = D["primary"]["P2prime"]
mm = lambda c: f"{f2(c['mean'])} ({f2(c['max'])})"
need(f"{100 * pp['median_abs_rel_error']:.1f}\\% (median $|e|$) & {mm(cp['cheapest_first@0.05'])} & {mm(cp['coast_d@0.05'])} & "
     f"{mm(cp['cheapest_first@0.25'])} & {mm(cp['coast_d@0.25'])} & {mm(cd['cheapest_first@0.05'])} & {mm(cd['cheapest_first@0.25'])} \\\\",
     MAIN, "table mean row")
need(f"supported, {pp['n_within_band']} of {pp['n_pairs']} within", MAIN, "table P2' decision")

# ---- P1' text
over = {c: [IDS[k] for k, v in enumerate(cp[c]["per_pair"]) if v > 1.25] for c in cp}
true(all(v == ["E2"] for v in over.values()), f"only E2 above 1.25: {over}")
rest = [v for c in cp for k, v in enumerate(cp[c]["per_pair"]) if IDS[k] != "E2"]
need(f"with values from {f2(min(rest))} to {f2(max(rest))}", MAIN, "non-E2 range")
e2 = {c: cp[c]["per_pair"][1] for c in cp}
need(f"spent {f2(e2['cheapest_first@0.05'])} times the 5\\% budget under cheapest-first and {f2(e2['coast_d@0.05'])} under COAST, "
     f"and {f2(e2['cheapest_first@0.25'])} and {f2(e2['coast_d@0.25'])} times the 25\\% budget", MAIN, "E2 values")
true(abs(cp["cheapest_first@0.25"]["mean"] - cp["coast_d@0.25"]["mean"]) < 0.005, "25% means equal at 2 dp")
need(f"The mean spend was {f2(cp['cheapest_first@0.05']['mean'])} (cheapest-first) and {f2(cp['coast_d@0.05']['mean'])} (COAST) at 5\\% "
     f"and {f2(cp['cheapest_first@0.25']['mean'])} at 25\\%", MAIN, "means")
true(e2["cheapest_first@0.05"] > 2.0, "E2 > 2.0 continuity")

# ---- P2' text
pe = D["primary"]["rel_error_per_pair"]
lo_i = min(pe, key=pe.get)
hi_i = max(pe, key=pe.get)
need(f"from {pctm(pe[lo_i])} ({lo_i}) to {pctm(pe[hi_i])} ({hi_i}), with a median absolute error of {100 * pp['median_abs_rel_error']:.1f}\\%",
     MAIN, "P2' range")
med = f"{100 * pp['median_abs_rel_error']:.1f}"

# ---- comparator
need(f"spent on average {f2(cd['cheapest_first@0.05']['mean'])} times the 5\\% budget (at most {f2(cd['cheapest_first@0.05']['max'])}, at E2) "
     f"and {f2(cd['cheapest_first@0.25']['mean'])} times the 25\\% budget (at most {f2(cd['cheapest_first@0.25']['max'])})", MAIN, "comparator")
true(cd["cheapest_first@0.05"]["per_pair"][1] == cd["cheapest_first@0.05"]["max"], "comparator max at E2")
need(f"at E2 from {f2(cd['cheapest_first@0.05']['per_pair'][1])} to {f2(cp['cheapest_first@0.05']['per_pair'][1])} and at E5 from "
     f"{f2(cd['cheapest_first@0.05']['per_pair'][4])} to {f2(cp['cheapest_first@0.05']['per_pair'][4])}", MAIN, "comparator E2/E5")
worse = max(cp[c]["per_pair"][k] - cd[c]["per_pair"][k] for c in cp for k in range(10))
true(worse <= 0.01, f"primary worse than comparator by {worse}")
need("never more than 0.01 worse")
need(f"median error {100 * D['phase_d_registered']['P2prime']['median_abs_rel_error']:.1f}\\% for RQ7's", MAIN, "comparator median")

# ---- diagnosis
x2 = XP["E2"]
need(f"({x2['new_file_price_primary_P99_s']:.3f}~s each, {x2['suite_cost']['new_file_est_s']:.2f}~s in total, against "
     f"{x2['suite_cost']['new_file_real_s']:.2f}~s real)", MAIN, "new-file prices E2")
cov = x2["new_file_coverage"]
true(cov["cheapest_first@0.05"]["selected_primary"] == 0 and cov["cheapest_first@0.25"]["selected_primary"] == 0
     and XP["E5"]["new_file_coverage"]["cheapest_first@0.05"]["selected_primary"] == 0
     and XP["E5"]["new_file_coverage"]["cheapest_first@0.25"]["selected_primary"] == 0, "no new-file test in CF plans")
true(cov["coast_d@0.05"]["selected_primary"] == len(nf2), "COAST one per file")
lane = {i: P[i]["estimators"]["primary"]["lane_cost_ratio"]["0.05"] for i in ("E2", "E5")}
need(f"{f2(lane['E2'])} (E2) and {f2(lane['E5'])} (E5) of the 5\\% budget", MAIN, "lane cost")
sp = X["summary"]["spend_ratio_seen_part_vs_unseen_part"]["E2"]["cheapest_first@0.05"]
need(f"Of E2's {f2(e2['cheapest_first@0.05'])} at 5\\%, seen tests account for {f2(sp['seen'])}", MAIN, "seen share")
oc = x2["outcome_change_seen"]
big = max(oc["skipped_to_run_tests"], key=lambda t: t["real_s"])
true(big["test"].startswith("test/python/compiler/test_transpiler.py"), "skipped test file")
need(f"P duration of {1000 * big['est_s']:.1f}~ms", MAIN, "skipped est")
need(f"ran for {big['real_s']:.1f}~s", MAIN, "skipped real")
w5 = x2["worst_test_cheapest_first"]["0.05"]
w25 = x2["worst_test_cheapest_first"]["0.25"]
true(w5["worst_test"] == big["test"] == w25["worst_test"], "worst test is the skipped one")
need(f"cost {f2(w5['real_over_budget'])} times the 5\\% budget and {f2(w25['real_over_budget'])} times the 25\\% budget", MAIN, "skipped share")
need(f"spent {f2(w5['spend_ratio_without_worst_test'])} and {f2(w25['spend_ratio_without_worst_test'])} times the budget", MAIN, "without it")
true(w25["spend_ratio_without_worst_test"] <= 1.25 < w5["spend_ratio_without_worst_test"], "25% alone decides")
true(all(X["summary"]["skipped_on_P_run_on_B"][i]["n"] == 0 for i in IDS if i != "E2"), "no other skipped-to-run")
seen5 = x2["spend_split_primary"]["cheapest_first@0.05"]["by_source"]["seen"]
b5 = P["E2"]["estimators"]["primary"]["budgets_s"]["0.05"]
ex = (seen5["real_over_budget"] * b5 - big["real_s"]) / (seen5["est_over_budget"] * b5 - big["est_s"])
sd = x2["seen_drift"]
need(f"the other {seen5['n_selected'] - 1:,} seen tests in the 5\\% plan, with a median P duration of {sd['seen_selected_5pct_median_est_ms']:.2f}~ms, "
     f"cost {f2(ex)} times their P durations (median {f2(sd['seen_selected_5pct_median_per_test_real_over_est'])} per test)", MAIN, "slowdown")
oth = [XP[i]["seen_drift"]["seen_selected_5pct_median_per_test_real_over_est"] for i in IDS if i != "E2"]
need(f"median per-test ratio was {f2(min(oth))} to {f2(max(oth))}", MAIN, "other pairs drift")
need(f"gives {sd['within_B_self_selection_pass1_to_pass2_spend_5pct']:.3f}", MAIN, "self-selection")
need(f"about {ex:.1f} times slower", MAIN, "practitioner bullet slowdown")

# ---- abstract, intro, conclusion, cover letter
a = re.search(r"\\abstract\{(.*?)\}\n", MAIN, re.S).group(1)
words_n = len(a.replace("\\%", "%").split())
true(words_n <= 250, f"abstract {words_n} words")
need(f"median error of {med}\\%", a, "abstract median")
need(f"overspent {f2(e2['cheapest_first@0.05'])}-fold", a, "abstract E2")
need("Nine pairs stayed within 1.25 times the budget", a, "abstract nine pairs")
need("ten fresh release pairs", a, "abstract ten pairs")
need("We answer eight research questions")
need("\\item[RQ8 (third confirmation).]")
need(f"median error of {med}\\%, every pair within $\\pm 25\\%$, and kept nine of ten pairs within 1.25 times the budget", MAIN, "contribution")
need(f"(median error {med}\\%), and nine pairs stayed within 1.25 times the budget, but one minor release overspent "
     f"{f2(e2['cheapest_first@0.05'])}-fold", MAIN, "conclusion")
need(f"median error {med}%", COVER, "cover letter median")
need(f"{f2(e2['cheapest_first@0.05'])}-fold", COVER, "cover letter E2")
need("PHASE\\_E.md}, public commit \\texttt{dfc413c}", MAIN, "data availability")

# ---- style in the RQ8 section
sec = MAIN[MAIN.index("\\section{Third confirmation study (RQ8)"):MAIN.index("\\section{Discussion}")]
prose = re.sub(r"\\begin\{table\}.*?\\end\{table\}", "", sec, flags=re.S)
true("---" not in prose and "\u2014" not in prose, "em-dash in RQ8 section")
true(not re.search(r"[a-z]; [a-z]", prose), "semicolon joining clauses in RQ8 section")
true("---" not in MAIN and "\u2014" not in MAIN, "em-dash in main.tex")

# ---- OR1 section is the generator output
r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_or1_phasee.py"), "--check"], capture_output=True, text=True)
true(r.returncode == 0, "or1_phasee.tex differs from generator output")
need(f"{min(ks):.2f} to {max(ks):.2f}", OR1, "k range in OR1")

print(f"{n} checks, {len(fails)} failures; abstract {words_n} words")
for f in fails:
    print("  FAIL", f)
sys.exit(1 if fails else 0)
