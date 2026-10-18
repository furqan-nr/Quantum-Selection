"""Check every Phase D (RQ7) number used in the manuscript against the frozen sources.

Sources: results/phase_d_confirmatory.json, results/phase_d_exploratory_diagnostics.json,
phase_d/data/budget_lock/*.json, phase_d/data/collect/*/COMPLETE.json, phase_d/collection_notes.md.
Each expected string is computed from the sources (never typed) and must occur in the named file.
Also checks: OR1 section equals its generator output, abstract <= 250 words, no em-dash in the RQ7 text.
Usage: python verification/check_phase_d_manuscript.py   (exit 1 on any failure)
"""
import json
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "results/phase_d_confirmatory.json").read_text())
X = json.loads((ROOT / "results/phase_d_exploratory_diagnostics.json").read_text())
EV = {e["event_id"]: e for e in R["events"]}
IDS = [f"D{i}" for i in range(1, 9)]
MAIN = (ROOT / "paper/sqj/main.tex").read_text()
COVER = (ROOT / "paper/build_cover_letter_sqj.js").read_text()
NOTES = (ROOT / "phase_d/collection_notes.md").read_text() + (ROOT / "verification/phase_d_independent_check.md").read_text()
fails, n = [], 0


def need(s, where=MAIN, label=""):
    global n
    n += 1
    if s not in where:
        fails.append(f"missing: {label or s!r}")


def f2(x):
    return f"{x:.2f}"


def pctm(x):  # manuscript style: $+1.6\%$ / $-10.7\%$
    return ("$+" if x >= 0 else "$-") + f"{abs(100 * x):.1f}\\%$"


# ---- locks match results, k inside band
for i in IDS:
    lk = json.loads((ROOT / f"phase_d/data/budget_lock/{i}.json").read_text())
    n += 1
    if abs(lk["budgets_s"]["0.05"] - EV[i]["budgets_s"]["0.05"]) > 1e-9 or not EV[i]["budget_lock_matches"]:
        fails.append(f"lock mismatch {i}")
ks = [EV[i]["speed"]["k_measured"] for i in IDS]
need(f"{min(ks):.2f} to {max(ks):.2f}", (ROOT / "paper/sqj/or1_phased.tex").read_text(), "k range in OR1")
for c in ["32e53d4", "a3c1148", "25ad1e3"]:
    n += 1
    if c not in NOTES:
        fails.append(f"commit {c} not in collection notes")
    need(c, MAIN, f"commit {c}")

# ---- decisions
P1 = R["decisions"]["P1"]
n += 1
if P1["supported"] or R["decisions"]["P2"]["supported"]:
    fails.append("P1/P2 should be not supported")
c = P1["criteria"]
for pol in ["cheapest_first", "coast_d"]:
    need(f"{f2(c[pol + '@0.05']['mean'])} ({f2(c[pol + '@0.05']['max'])})", MAIN, f"P1 {pol} 5%")
    need(f"{f2(c[pol + '@0.25']['mean'])} ({f2(c[pol + '@0.25']['max'])})", MAIN, f"P1 {pol} 25%")
need(f"spent on average {f2(c['coast_d@0.05']['mean'])} times the pr budget (at most {f2(c['coast_d@0.05']['max'])}")
need(f"{f2(c['coast_d@0.25']['mean'])} times the nightly budget (at most {f2(c['coast_d@0.25']['max'])}")
# abstract / conclusion / cover letter
need(f"spent {f2(c['cheapest_first@0.05']['mean'])} times the 5\\% budget on average", MAIN, "abstract 2.74")
need(f"{f2(c['coast_d@0.25']['mean'])} times the 25\\% budget", MAIN, "conclusion 1.45")
need(f2(c["coast_d@0.05"]["mean"]), COVER, "cover letter 2.74")

# ---- P2 per event (main text sentence and table)
pe = R["decisions"]["P2"]["rel_error"]
within = [i for i in IDS if abs(pe[i]) <= 0.25]
n += 1
if len(within) != 6 or set(IDS) - set(within) != {"D2", "D6"}:
    fails.append("P2 within set")
for i in within:
    need(f"{i} {pctm(pe[i])}", MAIN, f"P2 sentence {i}")
need(pctm(pe["D2"]).replace("$", "(") if False else f"({pctm(pe['D2'])})", MAIN, "P2 D2/D6 117.3")
need(f"by {100 * pe['D2']:.0f}\\%", MAIN, "117% in text")
need(f"{EV['D2']['pre_existing_est_s']:.1f}~s against a real {EV['D2']['pre_existing_real_s']:.1f}~s")
for i in IDS:
    e = EV[i]
    t = e["policies"]["tiers"]
    a = e["policies"]["apfdc"]
    yn = lambda v: "yes" if v else "no"
    row = (f"{i} & {e['pre_existing_est_s']:.1f} & {e['pre_existing_real_s']:.1f} & {pctm(pe[i])} & "
           f"{f2(t['0.05']['coast_d']['spend_ratio'])} & {f2(t['0.25']['coast_d']['spend_ratio'])} & "
           f"{a['coast_d']:.3f} & {a['default']:.3f} & {a['random']:.3f} & "
           f"{yn(t['0.05']['coast_d']['detected'])} / {yn(t['0.25']['coast_d']['detected'])} \\\\")
    need(row, MAIN, f"Table row {i}")
    diff = max(abs(t[f]["coast_d"]["spend_ratio"] - t[f]["cheapest_first"]["spend_ratio"]) for f in ("0.05", "0.25"))
    n += 1
    if diff > 0.001:
        fails.append(f"cheapest-first vs COAST differs by {diff} on {i}")
m = {p: st.mean(EV[i]["policies"]["apfdc"][p] for i in IDS) for p in ["coast_d", "default", "random"]}
need(f"& {m['coast_d']:.3f} & {m['default']:.3f} & {m['random']:.3f} & 2 / 6", MAIN, "table mean row")

# ---- events table
ledger = {e["event_id"]: e for e in json.loads((ROOT / "phase_d/events/phase_d_events.json").read_text())["events"]}
for i in IDS:
    e = EV[i]
    new = X["events"][i]["a_P2_decomposition"]["B_tests_unseen_in_P"]
    need(f"{e['P']} $\\rightarrow$ {e['B']} $\\rightarrow$ {e['F']} & {e['suite_size']:,} & {new} & {e['detection']['n_detecting']} \\\\",
         MAIN, f"events row {i}")
    n += 1
    if (ledger[i]["P"], ledger[i]["B"], ledger[i]["F"]) != (e["P"], e["B"], e["F"]):
        fails.append(f"ledger mismatch {i}")
sizes = [EV[i]["suite_size"] for i in IDS]
need(f"{min(sizes):,} to {max(sizes):,}", MAIN, "suite size range")
b5 = [EV[i]["budgets_s"]["0.05"] for i in IDS]
b25 = [EV[i]["budgets_s"]["0.25"] for i in IDS]
need(f"{f2(min(b5))} to {f2(max(b5))}~s and {f2(min(b25))} to {f2(max(b25))}~s", MAIN, "budget ranges")
small = [i for i in IDS if X["events"][i]["a_P2_decomposition"]["B_tests_unseen_in_P"] <= 12]
n += 1
if small != ["D1", "D5", "D8"]:
    fails.append(f"small-churn events {small}")
need(f"gained at most {max(X['events'][i]['a_P2_decomposition']['B_tests_unseen_in_P'] for i in small)} new tests")
sp = [EV[i]["policies"]["tiers"]["0.05"]["coast_d"]["spend_ratio"] for i in small]
need(f"pr spend was {f2(min(sp))} to {f2(max(sp))} times the budget")
need(f"at or below {f2(max(sp))} times the budget")
need(f"On D3 it was {f2(EV['D3']['policies']['tiers']['0.05']['coast_d']['spend_ratio'])}, on D2 and D6 "
     f"{f2(EV['D2']['policies']['tiers']['0.05']['coast_d']['spend_ratio'])}, and on D4 and D7 "
     f"{f2(EV['D4']['policies']['tiers']['0.05']['coast_d']['spend_ratio'])}")

# ---- forecast checks
H1, H2 = R["decisions"]["H"]["H1"], R["decisions"]["H"]["H2"]
n += 1
if H1["supported"] or not H2["supported"] or H2["sign_test"]["wins"] != 8 or (H1["sign_test"]["wins"], H1["sign_test"]["losses"]) != (6, 2):
    fails.append("H1/H2 outcome")
need(f"mean APFDc difference ${H2['mean_d']:+.3f}$, Wilcoxon $p = {H2['wilcoxon']['p']:.4f}$, Holm $p = {H2['holm']['holm_p']:.4f}$")
need(f"mean ${H1['mean_d']:+.3f}$, $p = {H1['wilcoxon']['p']:.3f}$")
losers = [IDS[k] for k, d in enumerate(H1["d"]) if d < 0]
need(f"behind on {losers[0]} and {losers[1]}")
d1 = R["decisions"]["D1"]["tiers"]
n += 1
if not R["decisions"]["D1"]["supported"]:
    fails.append("detection rule")
need(f"on {d1['0.05']['counts']['coast_d']} events at the pr tier against {d1['0.05']['counts']['default']} for the default order, "
     f"none for the round robin and {d1['0.05']['counts']['random_expected']:.2f} expected")
need(f"on {d1['0.25']['counts']['coast_d']} at the nightly tier against {d1['0.25']['counts']['default']}, "
     f"{d1['0.25']['counts']['file_rr']} and {d1['0.25']['counts']['random_expected']:.2f}")
need(f"McNemar $p = {d1['0.05']['mcnemar_vs_default']['p']:.1f}$ and ${d1['0.25']['mcnemar_vs_default']['p']:.2f}$")
n += 1
if d1["0.05"]["counts"]["file_rr"] != 0 or sum(EV[i]["detection"]["n_detecting_pre_existing"] for i in IDS) != 0:
    fails.append("file_rr pr count or pre-existing detection")

# ---- post hoc diagnosis
seen = [X["events"][i]["b_P1_decomposition"]["0.05"]["by_estimate_source"]["seen"]["real_over_budget"] for i in IDS]
need(f"spent {f2(min(seen))} to {f2(max(seen))} times the pr budget", MAIN, "seen range")
newsp = {}
for i in IDS:
    b = X["events"][i]["b_P1_decomposition"]["0.05"]["by_estimate_source"]
    newsp[i] = sum(v["real_over_budget"] for k, v in b.items() if k != "seen")
need(f"added {f2(newsp['D2'])} budgets on D2/D6 and {f2(newsp['D4'])} on D4/D7")
pp = {f["file"].split("/")[-1]: f for f in X["events"]["D4"]["a_P2_decomposition"]["top_files"]}["test_two_qubit_peephole.py"]
need(f"the {pp['n']} tests of \\texttt{{test\\_two\\_qubit\\_peephole.py}}, new in 2.5.0, were priced at {pp['est_s']:.2f}~s in total and cost {pp['real_s']:.1f}~s")
wc = [X["events"][i]["b_winners_curse_and_noise"]["seen_selected_real_over_est_5pct"] for i in IDS]
spn = [X["events"][i]["b_winners_curse_and_noise"]["spearman_Bpass1_vs_Bpass2"] for i in IDS]
need(f"{f2(min(wc))} to {f2(max(wc))} times their estimate, Spearman between the B passes {f2(min(spn))} to {f2(max(spn))}")
d2 = X["events"]["D2"]
skf = {f["file"].split("/")[-1]: f for f in d2["a_P2_decomposition"]["top_files"]}
sku = {f["file"].split("/")[-1]: f for f in d2["b_P1_decomposition"]["0.05"]["top_unseen_files_in_plan"]}
sk = skf["test_solovay_kitaev.py"]
need(f"the {sk['est_sources']['seen']} tests present in both 2.0.3 and 2.1.0 were estimated at "
     f"{sk['est_s'] - sku['test_solovay_kitaev.py']['est_s']:.1f}~s and cost {sk['real_s'] - sku['test_solovay_kitaev.py']['real_s']:.1f}~s")
need(f"all {skf['test_template_matching.py']['n']} tests of \\texttt{{test\\_template\\_matching.py}} were skipped in 2.1.0")
need(f"error is ${100 * d2['a_P2_decomposition']['rel_error_excluding_top2_files']:+.1f}\\%$")
tails = X["c_phase_d_tails_median_over_events"]
syn = X["c_synthetic_corpus_tails (data_scaleup labels total_cost_s, per event)"]["median_over_events"]
need(f"carry {100 * tails['top1pct_share']:.0f}\\% of the real suite cost (median over events) against {100 * syn['top1pct_share']:.0f}\\%")
V = X["b_post_hoc_variants_summary"]
mean_cf = V["unseen_at_mean (file mean if >=3 seen, else global mean)"]["cheapest_first@0.05"]["mean"]
lane_cf = V["unseen_in_separate_always_run_lane"]["cheapest_first@0.05"]["mean"]
need(f"cheapest-first to {mean_cf:.2f} and {lane_cf:.2f} times the budget")
lane = max(X["events"][i]["b_post_hoc_variants"]["unseen_in_separate_always_run_lane"]["0.05"]["always_run_lane_over_budget"] for i in IDS)
need(f"costs up to {lane:.1f} times the pr budget on D4/D7")
wall = [X["events"][i]["b_fixed_overhead"]["B_pass1_wall_over_sum_durations"] for i in IDS]
coll = [json.loads((ROOT / f"phase_d/data/collect/{EV[i]['B']}/COMPLETE.json").read_text())["collect_s"] for i in IDS]
need(f"{min(wall):.1f} to {max(wall):.1f} times its summed test time, and collection alone {min(coll):.1f} to {max(coll):.1f}~s")

# ---- abstract
a = re.search(r"\\abstract\{(.*?)\}\n", MAIN, re.S).group(1)
words = len(a.replace("\\%", "%").split())
n += 1
if words > 250:
    fails.append(f"abstract {words} words")
need(f"by {100 * pe['D2']:.0f}\\%", a, "abstract 117%")

# ---- style in the RQ7 section
sec = MAIN[MAIN.index("\\section{Second confirmation study (RQ7)"):MAIN.index("\\section{Discussion}")]
prose = re.sub(r"\\begin\{table\}.*?\\end\{table\}", "", sec, flags=re.S)
n += 1
if "---" in prose or "\u2014" in prose:
    fails.append("em-dash in RQ7 section")
n += 1
if re.search(r"[a-z]; [a-z]", prose):
    fails.append("semicolon joining clauses in RQ7 section")

# ---- OR1 section is the generator output
n += 1
r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_or1_phased.py"), "--check"], capture_output=True, text=True)
if r.returncode != 0:
    fails.append("or1_phased.tex differs from generator output")

print(f"{n} checks, {len(fails)} failures; abstract {words} words")
for f in fails:
    print("  FAIL", f)
sys.exit(1 if fails else 0)
