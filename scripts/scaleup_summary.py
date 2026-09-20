"""Phase C4 (PAPER2_EMSE_SCALEUP_PLAN.md): effect sizes and bootstrap CIs for `decomposed` vs every
baseline and vs `proposed`, on the frozen n=19 scale-up mutation cohort.

`cart.metrics.evaluate()` already reports `proposed_vs_*` effect sizes and a per-selector bootstrap CI
in results/evaluation_scaleup_frozen.json (evaluate.py's own output). This script adds the
complementary `decomposed_vs_*` comparison table (Cliff's delta is anti-symmetric, so
decomposed_vs_proposed is recoverable from proposed_vs_decomposed, but decomposed_vs_diversity_only /
_vs_cheapest_first / etc. are not yet computed anywhere) using the exact same metric functions
(cart.metrics.curves) and the exact same committed evaluation output, so nothing is re-run or re-frozen.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cart.metrics.curves import bootstrap_ci, cliffs_delta, cliffs_magnitude, vargha_delaney_a12

SELECTORS = ["cheapest_first", "diversity_only", "history_only", "change_stage", "proposed", "decomposed"]


def main():
    src = ROOT / "results" / "evaluation_scaleup_frozen.json"
    d = json.loads(src.read_text())
    pe = d["per_event"]["mutation"]
    events = sorted(pe.keys())
    assert len(events) == 19, f"expected 19 scale-up mutation events, got {len(events)}"

    aucs = {s: [pe[k][s]["AUC"] for k in events] for s in SELECTORS}
    aucs["random"] = [pe[k]["random"]["AUC_median"] for k in events]

    by_selector_ci = {s: bootstrap_ci(aucs[s], n_boot=2000, alpha=0.05, seed=0) for s in SELECTORS + ["random"]}

    decomposed = aucs["decomposed"]
    decomposed_vs = {}
    for s in SELECTORS + ["random"]:
        if s == "decomposed":
            continue
        delta = cliffs_delta(decomposed, aucs[s])
        decomposed_vs[s] = {
            "cliffs_delta": delta,
            "magnitude": cliffs_magnitude(delta),
            "a12": vargha_delaney_a12(decomposed, aucs[s]),
            "mean_decomposed": round(sum(decomposed) / len(decomposed), 4),
            "mean_other": round(sum(aucs[s]) / len(aucs[s]), 4),
        }

    # win/tie/loss decomposed vs each other selector, per event (same convention as evaluate.py's
    # own proposed-vs-* table)
    wtl = {}
    for s in SELECTORS + ["random"]:
        if s == "decomposed":
            continue
        w = t = l = 0
        for k in events:
            dv = pe[k]["decomposed"]["AUC"]
            ov = pe[k]["random"]["AUC_median"] if s == "random" else pe[k][s]["AUC"]
            if dv > ov:
                w += 1
            elif dv < ov:
                l += 1
            else:
                t += 1
        wtl[s] = {"win": w, "tie": t, "loss": l}

    out = {
        "description": (
            "Phase C4: decomposed-selector effect sizes, bootstrap CIs, and win/tie/loss vs every "
            "baseline and vs proposed, on the frozen n=19 EMSE scale-up mutation cohort "
            "(results/evaluation_scaleup_frozen.json). Complements evaluate()'s own proposed_vs_* "
            "table (Cliff's delta is anti-symmetric: decomposed_vs_proposed here equals "
            "-1 * proposed_vs_decomposed in the evaluate() output, reported independently here for "
            "convenience, not a new computation)."
        ),
        "n_events": len(events),
        "events": events,
        "bootstrap_ci_by_selector": by_selector_ci,
        "decomposed_vs": decomposed_vs,
        "win_tie_loss_decomposed_vs": wtl,
    }
    dest = ROOT / "results" / "scaleup_summary.json"
    dest.write_text(json.dumps(out, indent=2))
    print(f"wrote {dest}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
