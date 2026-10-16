"""Event-dependence and own-oracle analyses (POST-HOC, NOT pre-registered; exploratory, added in response to
review). Frozen and previously written result files are only read, never written.

Writes results/revision_dependence.json with four sections:
  A. Event dependence on the scale-up cohort (data_scaleup/, 19 mutation events, 116 units): detection set of
     each event (units whose `detects` is True), pairwise Jaccard matrix, groups of events with identical
     detection sets (Jaccard = 1; two empty sets count as identical, Jaccard := 1), pairs with Jaccard >= 0.8,
     and the effective number of distinct events of the 116 x 19 detection matrix (distinct columns,
     Jaccard>=0.8 clusters, real rank, eigenvalue-based M_eff of the phi-correlation matrix).
  B. Robustness of three paired comparisons (proposed vs diversity_only, decomposed vs proposed, decomposed vs
     cheapest_first) to that dependence: (i) deduplication keeping one event per identical-set group
     (alphabetically first; plus every possible choice when the number of combinations is <= 64);
     (ii) cluster bootstrap over Jaccard>=0.8 clusters (5000 resamples, numpy default_rng(0));
     (iii) restriction to informative events (0 < detection fraction < 0.48). Each: mean r4 difference,
     wins/ties/losses, Wilcoxon p, exact sign-test p, exact paired sign-flip permutation p, cluster-bootstrap
     95% interval. The all-19 analysis is repeated as the reference. Supplementary: the same for the two
     comparisons against random (100-seed per-event means from results/revision_stats_extra.json).
  C. The two forward regressions scored with the study's OWN oracle pipeline instead of the fault-matched rules
     of scripts/forward_selector_eval.py: the quality oracle (cart.oracles.quality.evaluate_quality with
     configs/thresholds.yaml, called on duck-typed stand-ins that carry the stored (n2q, depth)) and the
     single-run performance screen (cart.oracles.performance.screen_performance, 20% threshold from
     configs/thresholds.yaml) on the FIRST wall-clock run (sensitivity: median of the runs; first CPU-time run).
     Overlap with the fault-matched detections, then selector AUC / tests-to-first-detection with
     "flagged by the pipeline" as detection, following forward_selector_eval.py (wall clock, costs = candidate
     median wall time + constant oracle estimate, empty history, SELECTORS_SCALEUP, random = mean of seeds 0..19).
  D. False-alarm estimate of the 20% single-run screen on the performance event's LAST-GOOD build against
     itself (baseline run 1 vs run 2; plus the reverse direction and all ordered run pairs).

Conventions follow scripts/revision_reanalysis.py / revision_stats_extra.py: per-event AUCs rounded to 4
decimals (r4) before differencing; Wilcoxon two-sided, zero_method="wilcox", method="auto"; Holm within the
3-comparison family of each analysis; matched-pairs rank-biserial; percentile bootstrap.

Run from repo root:  PYTHONPATH=src python scripts/revision_dependence.py
"""
from __future__ import annotations

import itertools
import json
import statistics
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml
from scipy.stats import wilcoxon, binomtest

from cart.metrics.curves import event_metrics
from cart.labels.ground_truth import LABEL_FOR_FAULT
from cart.metrics.evaluate import _build_payloads, _run_metrics
from cart.oracles.performance import screen_performance
from cart.oracles.quality import QualityThresholds, evaluate_quality, count_2q
from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import ORACLE_COST_EST
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "revision_dependence.json"
REANALYSIS = ROOT / "results" / "revision_reanalysis.json"
STATS_EXTRA = ROOT / "results" / "revision_stats_extra.json"
THRESHOLDS = ROOT / "configs" / "thresholds.yaml"
FWD = {"fwd-applylayout-registers-14904": ROOT / "results/forward_units/fwd-applylayout-registers-14904_v2.json",
       "hist-vf2postlayout-noop": ROOT / "results/forward_units/hist-vf2postlayout-noop_v2_corrected.json"}
FWD_STORED_SELECTORS = {"fwd-applylayout-registers-14904": ROOT / "results/forward_units/fwd-applylayout-registers-14904_v2_selectors.json",
                        "hist-vf2postlayout-noop": ROOT / "results/forward_units/hist-vf2postlayout-noop_v2_corrected_selectors.json"}
EXPECTED_FAULT_MATCHED = {"fwd-applylayout-registers-14904": 67, "hist-vf2postlayout-noop": 6}
COMPARISONS = [("proposed", "diversity_only"), ("decomposed", "proposed"), ("decomposed", "cheapest_first")]
SUPP_COMPARISONS = [("proposed", "random"), ("decomposed", "random")]
NEAR = 0.8                   # Jaccard threshold for "near-identical"
INFORMATIVE = (0.0, 0.48)    # open interval on the detection fraction
N_BOOT = 5000
MAX_COMBOS = 64
EXACT_PERM_MAX = 20
RATIO, ABS_DIFF = 1.5, 0.010   # forward_selector_eval.py performance rule
FWD_CLOCK = "wall_times_s"     # the amended (high-resolution) clock of forward_selector_eval.py
FWD_SEEDS = range(20)


def r4(x):
    return round(float(x), 4)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); out = [None] * len(ps); run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i])); out[i] = run
    return out


def rbc_d(d):
    d = np.asarray(d, float); d = d[np.abs(d) > 1e-9]
    if len(d) == 0: return 0.0
    r = np.argsort(np.argsort(np.abs(d))) + 1.0
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def wilcox_p(a, b):
    """Two-sided Wilcoxon p exactly as revision_reanalysis.py computes it (inputs already r4)."""
    if all(x == y for x, y in zip(a, b)): return 1.0
    try: return float(wilcoxon(a, b, zero_method="wilcox", method="auto").pvalue)
    except ValueError: return 1.0


def sign_p(w, l):
    return 1.0 if w + l == 0 else float(binomtest(w, w + l, 0.5, alternative="two-sided").pvalue)


def perm_p(d, seed=0):
    """Paired sign-flip permutation test of the mean difference (two-sided, statistic |sum d|).
    Zero differences cannot change sign and are dropped. Exact enumeration if <= EXACT_PERM_MAX nonzero."""
    d = np.asarray(d, float); nz = d[np.abs(d) > 1e-12]; n = len(nz)
    if n == 0: return dict(p=1.0, method="no nonzero differences", n_nonzero=0)
    obs = abs(nz.sum())
    if n <= EXACT_PERM_MAX:
        signs = ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1) * 2 - 1
        s = np.abs(signs @ nz)
        return dict(p=float(np.mean(s >= obs - 1e-12)), method="exact", n_nonzero=n, n_assignments=int(2 ** n))
    rng = np.random.default_rng(seed); signs = rng.choice([-1.0, 1.0], size=(200000, n))
    s = np.abs(signs @ nz)
    return dict(p=float((1 + np.sum(s >= obs - 1e-12)) / (1 + 200000)), method="monte_carlo_200000", n_nonzero=n)


def components(ids, J, thr):
    """Connected components (single linkage) of the graph with an edge when Jaccard >= thr."""
    idx = {e: k for k, e in enumerate(ids)}; seen, comps = set(), []
    for e in ids:
        if e in seen: continue
        stack, comp = [e], []
        seen.add(e)
        while stack:
            x = stack.pop(); comp.append(x)
            for y in ids:
                if y not in seen and J[idx[x]][idx[y]] >= thr - 1e-12:
                    seen.add(y); stack.append(y)
        comps.append(sorted(comp))
    return sorted(comps, key=lambda c: c[0])


def cluster_boot_ci(d_by_event, clusters, n=N_BOOT, seed=0):
    """Cluster (block) bootstrap of the mean paired difference: resample clusters with replacement (as many
    as there are clusters) and take the event-weighted mean over all events of the drawn clusters."""
    rng = np.random.default_rng(seed)
    sums = np.array([sum(d_by_event[e] for e in c) for c in clusters]); sizes = np.array([len(c) for c in clusters], float)
    k = len(clusters); draws = rng.integers(0, k, (n, k))
    m = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def event_boot_ci(d, n=N_BOOT, seed=0):
    """Ordinary event-level percentile bootstrap (as boot_mean_ci in revision_stats_extra.py)."""
    rng = np.random.default_rng(seed); d = np.asarray(d, float)
    m = d[rng.integers(0, len(d), (n, len(d)))].mean(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def compare(val, a, b, ids, clusters=None, boot=True):
    x = [val[a][i] for i in ids]; y = [val[b][i] for i in ids]
    d = [u - v for u, v in zip(x, y)]
    w = int(sum(u > v for u, v in zip(x, y))); l = int(sum(u < v for u, v in zip(x, y))); t = len(ids) - w - l
    row = dict(a=a, b=b, n_events=len(ids), mean_diff=float(np.mean(d)), wins=w, ties=t, losses=l,
               rank_biserial=rbc_d(d), p_wilcoxon=wilcox_p(x, y), p_sign_exact=sign_p(w, l))
    pp = perm_p(d); row["p_permutation"] = pp["p"]; row["permutation_method"] = pp["method"]
    if boot:
        row["event_bootstrap_ci95"] = event_boot_ci(d)
        if clusters is not None:
            dd = dict(zip(ids, d))
            row["cluster_bootstrap_ci95"] = cluster_boot_ci(dd, clusters)
            row["n_clusters"] = len(clusters)
    return row


def family(val, ids, comps, clusters=None, boot=True):
    rows = [compare(val, a, b, ids, clusters, boot) for a, b in comps]
    for key in ("p_wilcoxon", "p_sign_exact", "p_permutation"):
        for r, h in zip(rows, holm([r[key] for r in rows])): r[key + "_holm3"] = h
    return {f"{r['a']}_vs_{r['b']}": r for r in rows}


# ------------------------------------------------------------------------------------------------ A
def section_A(pay, ids):
    sets = {e: frozenset(t for t, v in pay[e]["detects"].items() if v) for e in ids}
    units = sorted(set().union(*[set(pay[e]["detects"]) for e in ids]))
    assert all(set(pay[e]["detects"]) == set(units) for e in ids), "events are not labelled on the same unit set"

    def jac(s, t):
        u = s | t
        return 1.0 if not u else len(s & t) / len(u)
    J = [[jac(sets[e], sets[f]) for f in ids] for e in ids]
    by_set = {}
    for e in ids: by_set.setdefault(sets[e], []).append(e)
    identical = sorted([sorted(g) for g in by_set.values() if len(g) > 1], key=lambda g: g[0])
    near_pairs = [dict(a=ids[i], b=ids[j], jaccard=J[i][j], n_a=len(sets[ids[i]]), n_b=len(sets[ids[j]]),
                       n_intersection=len(sets[ids[i]] & sets[ids[j]]), identical=J[i][j] == 1.0)
                  for i in range(len(ids)) for j in range(i + 1, len(ids)) if J[i][j] >= NEAR - 1e-12]
    near_pairs.sort(key=lambda r: (-r["jaccard"], r["a"], r["b"]))
    clusters = components(ids, J, NEAR)
    idx = {e: k for k, e in enumerate(ids)}
    cl_info = [dict(events=c, size=len(c), min_pairwise_jaccard=(min(J[idx[x]][idx[y]] for x, y in itertools.combinations(c, 2)) if len(c) > 1 else 1.0),
                    is_clique_at_threshold=all(J[idx[x]][idx[y]] >= NEAR - 1e-12 for x, y in itertools.combinations(c, 2)))
               for c in clusters]
    # effective number of distinct events
    M = np.array([[1.0 if pay[e]["detects"][t] else 0.0 for e in ids] for t in units])   # 116 x 19
    nonconst = [k for k in range(M.shape[1]) if 0 < M[:, k].sum() < M.shape[0]]
    C = np.corrcoef(M[:, nonconst], rowvar=False)
    lam = np.clip(np.linalg.eigvalsh(C), 0, None); m = len(nonconst)
    meff_nyholt = 1 + (m - 1) * (1 - np.var(lam, ddof=1) / m)
    meff_liji = float(sum((1.0 if x >= 1 else 0.0) + (x - np.floor(x)) for x in lam))
    pr = float(lam.sum() ** 2 / (lam ** 2).sum())
    n_const_groups = len({tuple(M[:, k]) for k in range(M.shape[1]) if k not in nonconst})
    eff = dict(
        n_events=len(ids), n_units=len(units),
        n_distinct_detection_sets=len(by_set),
        n_distinct_nonempty_detection_sets=len([s for s in by_set if s]),
        n_clusters_jaccard_ge_0_8=len(clusters),
        matrix_rank=int(np.linalg.matrix_rank(M)),
        eigen_based=dict(
            note=("phi (Pearson) correlation of the non-constant columns; constant columns (events no unit detects) "
                  "have no correlation and are excluded, then counted as `n_constant_column_groups` distinct pattern(s)"),
            n_nonconstant_columns=m, n_constant_column_groups=n_const_groups,
            participation_ratio=pr, meff_nyholt_2004=float(meff_nyholt), meff_li_ji_2005=meff_liji,
            participation_ratio_plus_constant=pr + n_const_groups, meff_li_ji_plus_constant=meff_liji + n_const_groups,
            eigenvalues_desc=[float(x) for x in sorted(lam, reverse=True)]))
    A = dict(
        definitions=dict(detection_set="units u with detects[u] True in _build_payloads(data_scaleup)",
                         jaccard="|S∩T|/|S∪T|; two empty sets are identical, Jaccard := 1",
                         near_identical=f"Jaccard >= {NEAR}", clusters=f"connected components (single linkage) of the Jaccard >= {NEAR} graph"),
        detection_set_size={e: len(sets[e]) for e in ids},
        detection_fraction={e: len(sets[e]) / len(units) for e in ids},
        detection_sets={e: sorted(sets[e]) for e in ids},
        jaccard_matrix=dict(events=ids, values=[[round(x, 6) for x in row] for row in J]),
        identical_groups=identical, near_identical_pairs=near_pairs,
        clusters_jaccard_ge_0_8=cl_info, effective_number_of_events=eff)
    return A, sets, J, identical, clusters


# ------------------------------------------------------------------------------------------------ B
def section_B(pay, ids, sets, J, identical, val):
    idx = {e: k for k, e in enumerate(ids)}
    in_group = {e for g in identical for e in g}
    singles = [e for e in ids if e not in in_group]

    def clusters_for(sub):
        Js = [[J[idx[x]][idx[y]] for y in sub] for x in sub]
        return components(sub, Js, NEAR)

    allc = clusters_for(ids)
    B = dict(comparisons=[f"{a}_vs_{b}" for a, b in COMPARISONS],
             difference="r4(a) - r4(b) per event; positive = a better (higher AUC)",
             sources=dict(deterministic="results/revision_reanalysis.json per_event[event][selector]['auc']",
                          random="results/revision_stats_extra.json A_random_100_seeds.scaleup.per_event_mean_auc (supplementary only)"),
             tests=dict(wilcoxon="two-sided, zero_method='wilcox', method='auto' (scipy), on r4 values",
                        sign_test="exact two-sided binomial on wins vs losses (ties dropped)",
                        permutation=f"paired sign-flip of the nonzero r4 differences, statistic |sum|, exact when <= {EXACT_PERM_MAX} nonzero",
                        holm3="Holm within the 3 comparisons of the same analysis variant",
                        event_bootstrap="percentile, events resampled, 5000, default_rng(0) (reference)",
                        cluster_bootstrap=(f"percentile, Jaccard>={NEAR} clusters (within the analysed subset) resampled with replacement, "
                                           "event-weighted mean of the drawn clusters, 5000, default_rng(0) fresh per quantity")))
    B["all19_reference"] = dict(events=ids, clusters=allc, results=family(val, ids, COMPARISONS, allc))
    # (i) dedup
    dedup = sorted(singles + [g[0] for g in identical])
    cd = clusters_for(dedup)
    B["i_dedup_identical_alphabetical_first"] = dict(
        rule="keep the alphabetically first event of each identical-detection-set group", kept=dedup,
        dropped=sorted(set(ids) - set(dedup)), clusters=cd, results=family(val, dedup, COMPARISONS, cd))
    n_comb = int(np.prod([len(g) for g in identical])) if identical else 1
    enum = dict(n_combinations=n_comb, enumerated=n_comb <= MAX_COMBOS)
    if n_comb <= MAX_COMBOS:
        per_choice = []
        for choice in itertools.product(*identical):
            sub = sorted(singles + list(choice))
            res = family(val, sub, COMPARISONS, boot=False)
            per_choice.append(dict(kept=list(choice), results={k: {f: v[f] for f in ("mean_diff", "wins", "ties", "losses", "p_wilcoxon", "p_sign_exact", "p_permutation")}
                                                                for k, v in res.items()}))
        summ = {}
        for a, b in COMPARISONS:
            k = f"{a}_vs_{b}"; rs = [pc["results"][k] for pc in per_choice]
            s = {}
            for f in ("mean_diff", "p_wilcoxon", "p_sign_exact", "p_permutation"):
                s[f + "_range"] = [min(r[f] for r in rs), max(r[f] for r in rs)]
            s["wins_ties_losses_set"] = sorted({(r["wins"], r["ties"], r["losses"]) for r in rs})
            s["mean_diff_sign_invariant"] = len({np.sign(round(r["mean_diff"], 12)) for r in rs}) == 1
            for f in ("p_wilcoxon", "p_sign_exact", "p_permutation"):
                s[f + "_lt_0_05_invariant"] = len({r[f] < 0.05 for r in rs}) == 1
            s["fully_invariant"] = (len(s["wins_ties_losses_set"]) == 1 and s["mean_diff_range"][1] - s["mean_diff_range"][0] < 1e-12
                                    and all(s[f + "_range"][1] - s[f + "_range"][0] < 1e-12 for f in ("p_wilcoxon", "p_sign_exact", "p_permutation")))
            summ[k] = s
        enum.update(summary=summ, per_choice=per_choice)
    B["i_dedup_all_choices"] = enum
    # (ii) cluster bootstrap is reported inside every variant as cluster_bootstrap_ci95; also a cluster-level
    #      (one value per cluster = mean difference of its events) set of tests as a supplementary view
    cl_val = {}
    for s in val:
        cl_val[s] = {c[0]: float(np.mean([val[s][e] for e in c])) for c in allc}
    cl_ids = [c[0] for c in allc]
    B["ii_cluster_level"] = dict(
        note=("cluster-bootstrap intervals are reported in each variant's results (cluster_bootstrap_ci95). Here, additionally, each "
              "Jaccard>=0.8 cluster is collapsed to the mean of its events' r4 AUCs and the tests are run across clusters "
              "(cluster means are not re-rounded; ties are exact equality of cluster means)."),
        clusters=allc, results=family(cl_val, cl_ids, COMPARISONS, boot=False))
    # (iii) informative
    frac = {e: len(sets[e]) / len(pay[e]["detects"]) for e in ids}
    inf_ids = [e for e in ids if INFORMATIVE[0] < frac[e] < INFORMATIVE[1]]
    ci = clusters_for(inf_ids)
    B["iii_informative"] = dict(rule=f"{INFORMATIVE[0]} < detection fraction < {INFORMATIVE[1]}", events=inf_ids,
                                excluded={e: frac[e] for e in ids if e not in inf_ids}, clusters=ci,
                                results=family(val, inf_ids, COMPARISONS, ci))
    # supplementary: comparisons against random (100-seed means)
    B["supplementary_vs_random100"] = {
        "all19": family(val, ids, SUPP_COMPARISONS, allc),
        "dedup_alphabetical_first": family(val, dedup, SUPP_COMPARISONS, cd),
        "informative": family(val, inf_ids, SUPP_COMPARISONS, ci)}
    return B


# ------------------------------------------------------------------------------------------------ C / D
class _Circ:
    """Duck-typed stand-in exposing exactly what evaluate_quality reads: .data (instructions whose .operation has
    .num_qubits and .name) and .depth(). It carries n2q two-qubit 'cx' instructions and the stored depth."""
    def __init__(self, n2q, depth):
        op = SimpleNamespace(num_qubits=2, name="cx")
        self.data = [SimpleNamespace(operation=op)] * int(n2q); self._d = int(depth)

    def depth(self):
        return self._d


def quality_by_hand(b2, c2, bd, cd, th):
    """Independent re-implementation of evaluate_quality's rule on numbers (cross-check only)."""
    rel = lambda b, c: (0.0 if c == 0 else float("inf")) if b == 0 else (c - b) / b
    r2, rd = rel(b2, c2), rel(bd, cd)
    return (r2 >= th.tau_2q and -rd < th.tau_depth_improve) or (rd >= th.tau_depth and -r2 < th.tau_2q_improve)


def fault_matched(kind, rec):
    b, c = rec["baseline"], rec["candidate"]
    if b.get("status") != "ok" or c.get("status") != "ok": return None
    if kind == "contract_metadata": return b.get("registers") != c.get("registers")
    mb, mc = statistics.median(b[FWD_CLOCK]), statistics.median(c[FWD_CLOCK])
    return bool(mc / max(mb, 1e-9) >= RATIO and (mc - mb) >= ABS_DIFF)


def overlap(flag, fm):
    F = {t for t, v in flag.items() if v}; G = {t for t, v in fm.items() if v}
    return dict(n_flagged=len(F), n_fault_matched=len(G), n_both=len(F & G), n_flagged_not_fault_matched=len(F - G),
                n_fault_matched_not_flagged=len(G - F), flagged_units=sorted(F))


def section_C_D(sanity):
    th = QualityThresholds.load(THRESHOLDS)
    perf_thr = float(yaml.safe_load(THRESHOLDS.read_text())["performance"]["stage1_slowdown_threshold"])
    ctx0 = SelectionContext.load(ROOT / "data_scaleup", events_path=ROOT / "data" / "events" / "events.json")
    C = dict(
        replication=dict(
            quality=("cart.oracles.quality.evaluate_quality is called unchanged with thresholds QualityThresholds.load(configs/thresholds.yaml) "
                     f"({th.__dict__}) on duck-typed stand-ins: count_2q(stand-in) returns the stored n2q and .depth() the stored depth. "
                     "A hand re-implementation of rules 1/2 is run alongside and must agree on every unit."),
            quality_assumption=("stored n2q = count of {cx, cz, ecr, swap} ops of the transpiled output (scripts/forward_probe_units.py), whereas count_2q counts every "
                                "2-qubit op except barrier. With basis_gates [cx, rz, sx, x] the outputs contain no other 2-qubit op, so the two coincide; "
                                "this cannot be re-checked without the circuits. Stored depth = QuantumCircuit.depth(), as in evaluate_quality."),
            performance=(f"cart.oracles.performance.screen_performance(baseline_times, candidate_times, slowdown_threshold={perf_thr}) "
                         "(performance.stage1_slowdown_threshold of configs/thresholds.yaml). Primary: one-element lists holding the FIRST "
                         "wall-clock run of each build (cf. historical_runner.run_historical_event, which screens one cold run per build in a fresh "
                         "subprocess). Sensitivity: median of all runs (wall), and the first CPU-process-time run (the instrument historical_worker "
                         "records; 15.6 ms resolution on Windows, and screen_performance returns ratio 0 when the baseline time is 0)."),
            not_replicable=("the semantic/functional oracles (and their precedence over quality/performance in the label hierarchy) need the "
                            "circuits, which are not stored; 'flagged' therefore means quality regression OR performance screen, and the "
                            "label precedence quality > performance is applied only to name the label."),
            detection_for_selectors="pipeline_first = quality OR first-run wall screen (primary); pipeline_median = quality OR median wall screen; also quality-only and screen-only",
            selector_eval=("as scripts/forward_selector_eval.py with --clock wall: cost = median candidate wall time + ORACLE_COST_EST[oracle_type] (0.05 default); "
                           "baseline_costs = median baseline wall time; history = []; ctx units = the 116 usable units; ranking with SELECTORS_SCALEUP at an "
                           "infinite budget, seed 0 (random: mean over seeds 0..19); tests_to_first_detection = 1-based position of the first detecting "
                           "unit, len(ranking)+1 if none. The budget-tier (pr/nightly) part of that script is not repeated.")),
        events={})
    D = {}
    for eid, path in FWD.items():
        raw = json.loads(path.read_text()); recs = raw["records"]
        ev = ctx0.events[eid]; kind = ev.fault_type.value
        usable = {t: r for t, r in recs.items() if fault_matched(kind, r) is not None and t in ctx0.units}
        fm = {t: fault_matched(kind, r) for t, r in usable.items()}
        n_fm = int(sum(fm.values()))
        sanity[f"fault_matched_count_{eid}"] = dict(reproduced=n_fm, expected=EXPECTED_FAULT_MATCHED[eid], n_usable=len(usable))
        assert n_fm == EXPECTED_FAULT_MATCHED[eid], f"{eid}: fault-matched count {n_fm} != {EXPECTED_FAULT_MATCHED[eid]}"
        q, qd, pf, pm, pc = {}, {}, {}, {}, {}
        hand_mismatch = []
        for t, r in usable.items():
            b, c = r["baseline"], r["candidate"]
            bo, co = _Circ(b["n2q"], b["depth"]), _Circ(c["n2q"], c["depth"])
            assert count_2q(bo) == b["n2q"] and count_2q(co) == c["n2q"]
            res = evaluate_quality(bo, co, th)
            q[t] = bool(res.is_regression); qd[t] = dict(rule=res.rule_fired, rel_2q=res.rel_2q, rel_depth=res.rel_depth,
                                                           n2q=[b["n2q"], c["n2q"]], depth=[b["depth"], c["depth"]])
            if quality_by_hand(b["n2q"], c["n2q"], b["depth"], c["depth"], th) != q[t]: hand_mismatch.append(t)
            pf[t] = bool(screen_performance([b[FWD_CLOCK][0]], [c[FWD_CLOCK][0]], perf_thr).suspected_regression)
            pm[t] = bool(screen_performance(b[FWD_CLOCK], c[FWD_CLOCK], perf_thr).suspected_regression)
            pc[t] = bool(screen_performance([b["cpu_times_s"][0]], [c["cpu_times_s"][0]], perf_thr).suspected_regression)
        sanity[f"quality_hand_reimplementation_mismatches_{eid}"] = len(hand_mismatch)
        assert not hand_mismatch, hand_mismatch
        defs = {"fault_matched": fm,
                "pipeline_first": {t: q[t] or pf[t] for t in usable},
                "pipeline_median": {t: q[t] or pm[t] for t in usable},
                "pipeline_first_cpu": {t: q[t] or pc[t] for t in usable},
                "quality_only": q, "perf_screen_first_only": pf, "perf_screen_median_only": pm}
        labels = {t: ("quality_regression" if q[t] else "performance_regression" if pf[t] else "pass") for t in usable}
        # selector evaluation (forward_selector_eval.py approach, wall clock)
        base_med = {t: statistics.median(r["baseline"][FWD_CLOCK]) for t, r in usable.items()}
        cand_med = {t: statistics.median(r["candidate"][FWD_CLOCK]) for t, r in usable.items()}
        orc = {t: ORACLE_COST_EST.get(ctx0.units[t].oracle_type, 0.05) for t in usable}
        cost = {t: cand_med[t] + orc[t] for t in usable}
        ctx = replace(ctx0, units={t: ctx0.units[t] for t in usable}, baseline_costs={(eid, t): base_med[t] for t in usable}, history=[])
        sel_res = {k: {} for k in defs}
        for n, sel in SELECTORS_SCALEUP.items():
            seeds = list(FWD_SEEDS) if n == "random" else [0]
            rks = [[t for t in sel(ctx, eid, float("inf"), seed=s) if t in cost] for s in seeds]
            for k, det in defs.items():
                rows = []
                for rk in rks:
                    em = event_metrics(rk, cost, det)
                    first = next((i + 1 for i, t in enumerate(rk) if det.get(t)), None)
                    rows.append((em.auc_detection_vs_budget, em.normalized_ttfr, first if first else len(rk) + 1))
                sel_res[k][n] = dict(auc=float(np.mean([x[0] for x in rows])), normalized_ttfr=float(np.mean([x[1] for x in rows])),
                                     tests_to_first_detection=float(np.mean([x[2] for x in rows])))
        stored = json.loads(FWD_STORED_SELECTORS[eid].read_text())["selectors"]
        sanity[f"fault_matched_selector_auc_max_abs_diff_vs_stored_{eid}"] = max(abs(sel_res["fault_matched"][n]["auc"] - stored[n]["auc"]) for n in stored)
        sanity[f"fault_matched_tests_to_first_max_abs_diff_vs_stored_{eid}"] = max(abs(sel_res["fault_matched"][n]["tests_to_first_detection"] - stored[n]["tests_to_first_detection"]) for n in stored)
        C["events"][eid] = dict(
            source=str(path.relative_to(ROOT)).replace("\\", "/"), fault_type=kind, n_units=len(usable), repeats=raw.get("repeats"),
            fault_matched_rule="registers differ" if kind == "contract_metadata" else f"median wall ratio >= {RATIO} and difference >= {ABS_DIFF} s",
            n_fault_matched=n_fm,
            quality_oracle=dict(n_flagged=int(sum(q.values())),
                                rule_counts={k: sum(1 for t in usable if qd[t]["rule"] == k) for k in ("rule1_2q_worse", "rule2_depth_worse")},
                                n_units_n2q_changed=sum(1 for t in usable if qd[t]["n2q"][0] != qd[t]["n2q"][1]),
                                n_units_depth_changed=sum(1 for t in usable if qd[t]["depth"][0] != qd[t]["depth"][1]),
                                n_units_improved_2q_or_depth=sum(1 for t in usable if qd[t]["n2q"][1] < qd[t]["n2q"][0] or qd[t]["depth"][1] < qd[t]["depth"][0]),
                                flagged={t: qd[t] for t in usable if q[t]}),
            perf_screen_counts=dict(first_run_wall=int(sum(pf.values())), median_wall=int(sum(pm.values())), first_run_cpu=int(sum(pc.values()))),
            pipeline_label_counts={k: sum(1 for v in labels.values() if v == k) for k in ("quality_regression", "performance_regression", "pass")},
            label_matched_detection=dict(
                expected_label=LABEL_FOR_FAULT.get(ev.fault_type),
                n_units=sum(1 for v in labels.values() if v == LABEL_FOR_FAULT.get(ev.fault_type)),
                note=("number of units whose pipeline label (first-run screen) equals cart.labels.ground_truth.LABEL_FOR_FAULT[fault_type], "
                      "i.e. the study's own fault_id_detected rule; quality/performance labels cannot match a contract_metadata event")),
            overlap_with_fault_matched={k: overlap(v, fm) for k, v in defs.items() if k != "fault_matched"},
            selectors=sel_res,
            selectors_note="per detection definition; an AUC of 0 and tests_to_first_detection = n_units+1 mean no unit is flagged")
        # D: screen on a build against itself
        def self_screen(build, clock):
            runs = [r[build][clock] for r in usable.values()]; k = len(runs[0])
            pair = lambda i, j: int(sum(screen_performance([x[i]], [x[j]], perf_thr).suspected_regression for x in runs))
            allp = {f"{i+1}->{j+1}": pair(i, j) for i in range(k) for j in range(k) if i != j}
            warm = {key: v for key, v in allp.items() if "1" not in key.split("->")}
            return dict(n_runs=k, run1_vs_run2=pair(0, 1) if k > 1 else None, run2_vs_run1=pair(1, 0) if k > 1 else None,
                        all_ordered_pairs=allp, mean_rate_all_ordered_pairs=float(np.mean(list(allp.values())) / len(runs)) if allp else None,
                        mean_rate_pairs_excluding_run1=float(np.mean(list(warm.values())) / len(runs)) if warm else None)
        D[eid] = dict(role=("PRIMARY (performance event, last-good build a18e151 after the documented baseline/candidate label correction)"
                            if kind == "performance" else "supplementary (contract event; only 2 runs per build)"),
                      n_units=len(usable),
                      baseline_last_good={"wall": self_screen("baseline", FWD_CLOCK), "cpu": self_screen("baseline", "cpu_times_s")},
                      candidate_supplementary={"wall": self_screen("candidate", FWD_CLOCK)})
    D["definition"] = ("'a->b' = number of units flagged by screen_performance([run a], [run b], 0.20), run a in the baseline role and run b in "
                       "the candidate role, both runs from the SAME build; any flag is a false alarm. Rates are per unit (/n_units). "
                       "Run 1 of every unit is the first transpile in a fresh process (cold), so pairs with run 1 mix a warm-up effect "
                       "into the comparison; 'excluding run 1' uses only warm runs. The cold-vs-cold comparison that the primary "
                       "first-run screen of section C makes cannot be reproduced within one build (one cold run per unit and build).")
    return C, D


def main():
    sanity = {}
    res = {"description": (
        "POST-HOC analyses (not pre-registered) of event dependence (A, B) and of the forward regressions under the study's own oracles "
        "(C, D); produced by scripts/revision_dependence.py. Inputs are only read. A/B use the 19 scale-up mutation events "
        "(data_scaleup/); C/D use results/forward_units/*_v2(.corrected).json."),
        "conventions": {"rounding": "r4 (4 decimals) before differencing/testing",
                        "wilcoxon": "two-sided, zero_method='wilcox', method='auto'", "holm": "within the 3 comparisons of one analysis variant",
                        "rank_biserial": "matched-pairs, positive = a better", "bootstrap": "percentile, 5000 resamples, numpy default_rng(0) fresh per quantity"}}
    pay = {p["event_id"]: p for p in _build_payloads(ROOT / "data_scaleup", None, "all")}
    ids = sorted(pay)
    prev = json.loads(REANALYSIS.read_text())["per_event"]
    sx = json.loads(STATS_EXTRA.read_text())
    rnd = sx["A_random_100_seeds"]["scaleup"]["per_event_mean_auc"]
    assert sorted(prev) == ids and sorted(rnd) == ids
    names = sorted({s for c in COMPARISONS for s in c})
    # sanity: recompute the stored deterministic AUCs
    recomputed = {}
    for e in ids:
        for n in names:
            em, _ = _run_metrics(SELECTORS_SCALEUP[n], pay[e]["ctx"], e, pay[e]["cost"], pay[e]["detects"])
            recomputed[(e, n)] = em.auc_detection_vs_budget
    sanity["per_event_auc_max_abs_diff_recomputed_vs_reanalysis_json"] = max(abs(recomputed[(e, n)] - prev[e][n]["auc"]) for e in ids for n in names)
    assert sanity["per_event_auc_max_abs_diff_recomputed_vs_reanalysis_json"] < 1e-12
    val = {n: {e: r4(prev[e][n]["auc"]) for e in ids} for n in names}
    val["random"] = {e: r4(rnd[e]) for e in ids}

    A, sets, J, identical, clusters = section_A(pay, ids)
    sanity["detection_set_sizes_match_reanalysis_detection_fraction"] = all(
        len(sets[e]) == json.loads(REANALYSIS.read_text())["detection_fraction"][e]["detecting"] for e in ids)
    res["A_event_dependence"] = A
    B = section_B(pay, ids, sets, J, identical, val)
    # sanity: the all-19 reference reproduces revision_stats_extra.json F (paired table)
    F = {(r["a"], r["b"]): r for r in sx["F_paired_family7_random100"]}
    chk = {}
    for a, b in COMPARISONS + SUPP_COMPARISONS:
        mine = (B["all19_reference"]["results"] if (a, b) in COMPARISONS else B["supplementary_vs_random100"]["all19"])[f"{a}_vs_{b}"]
        flip = (a, b) not in F
        ref = F[(b, a)] if flip else F[(a, b)]
        chk[f"{a}_vs_{b}"] = dict(
            mean_diff_abs_diff=abs(mine["mean_diff"] - (-ref["mean_diff"] if flip else ref["mean_diff"])),
            p_wilcoxon_abs_diff=abs(mine["p_wilcoxon"] - ref["p"]),
            wtl_equal=(mine["wins"], mine["ties"], mine["losses"]) == ((ref["losses"], ref["ties"], ref["wins"]) if flip else (ref["wins"], ref["ties"], ref["losses"])),
            event_bootstrap_ci_abs_diff=(None if flip else max(abs(x - y) for x, y in zip(mine["event_bootstrap_ci95"], ref["diff_ci95"]))))
    sanity["all19_reference_vs_revision_stats_extra_F"] = chk
    assert all(v["mean_diff_abs_diff"] < 1e-12 and v["p_wilcoxon_abs_diff"] < 1e-12 and v["wtl_equal"] for v in chk.values())
    res["B_dependence_robustness"] = B
    C, D = section_C_D(sanity)
    res["C_forward_events_own_oracles"] = C
    res["D_single_run_screen_false_alarms"] = D
    res["sanity_checks"] = sanity
    if OUT.exists():
        print("note: overwriting this script's own previous output", OUT)
    OUT.write_text(json.dumps(res, indent=1, default=float)); print("wrote", OUT)
    # console summary
    print("A distinct sets", A["effective_number_of_events"]["n_distinct_detection_sets"], "identical groups", identical)
    for k in ("all19_reference", "i_dedup_identical_alphabetical_first", "iii_informative"):
        for c, r in B[k]["results"].items():
            print(k, c, round(r["mean_diff"], 4), (r["wins"], r["ties"], r["losses"]), round(r["p_wilcoxon"], 4),
                  round(r["p_sign_exact"], 4), round(r["p_permutation"], 4), [round(x, 4) for x in r["cluster_bootstrap_ci95"]])
    for e, v in C["events"].items():
        print(e, "quality", v["quality_oracle"]["n_flagged"], "perf", v["perf_screen_counts"], {k: (o["n_flagged"], o["n_both"]) for k, o in v["overlap_with_fault_matched"].items()})
    print(json.dumps(sanity, indent=1, default=float))


if __name__ == "__main__":
    main()
