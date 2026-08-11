"""Post-hoc (exploratory, not pre-registered) robustness check for the manuscript's headline
RQ2 comparison (§6.3): recompute the mean-AUC / effect-size comparison on the mutation cohort
with the two known-weak mutation types (insert_redundant_cx_pair, insert_redundant_x_pair)
excluded, using the exact same metric functions (cart.metrics.curves) and the exact same
committed evaluation output (results/evaluation_costhet_frozen.json) as the primary result.

This does NOT change, re-run, or re-freeze anything. It is a diagnostic re-aggregation of
already-frozen, already-reported per-event numbers, added in response to a peer-review request
to check how much of the headline effect size is concentrated in the two events already
identified (§6.4) as the selector's weak point. Labeled explicitly as exploratory in the paper.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cart.metrics.curves import bootstrap_ci, cliffs_delta, cliffs_magnitude, vargha_delaney_a12

EXCLUDE = {"mut-insert-redundant-cx-01", "mut-insert-redundant-x-01"}
SELECTORS = ["cheapest_first", "diversity_only", "history_only", "change_stage", "proposed"]


def main():
    src = ROOT / "results" / "evaluation_costhet_frozen.json"
    d = json.loads(src.read_text())
    pe = d["per_event"]["mutation"]

    kept = [k for k in pe if k not in EXCLUDE]
    assert len(kept) == 7, f"expected 7 kept events, got {len(kept)}"
    assert EXCLUDE <= set(pe.keys()), "excluded event ids not found in per_event data"

    aucs = {s: [pe[k][s]["AUC"] for k in kept] for s in SELECTORS}
    aucs["random"] = [pe[k]["random"]["AUC_median"] for k in kept]

    by_selector = {}
    for s in SELECTORS + ["random"]:
        by_selector[s] = bootstrap_ci(aucs[s], n_boot=2000, alpha=0.05, seed=0)

    proposed = aucs["proposed"]
    effect_sizes = {}
    for s in SELECTORS + ["random"]:
        if s == "proposed":
            continue
        delta = cliffs_delta(proposed, aucs[s])
        effect_sizes[s] = {
            "cliffs_delta": delta,
            "magnitude": cliffs_magnitude(delta),
            "a12": vargha_delaney_a12(proposed, aucs[s]),
        }

    out = {
        "description": (
            "Post-hoc, exploratory robustness check: mutation-cohort comparison with the two "
            "dominant-loss events (insert_redundant_cx_pair, insert_redundant_x_pair) excluded. "
            "Not a re-freeze; the primary frozen result (n=9, results/evaluation_costhet_frozen.json) "
            "is unchanged and remains the pre-registered headline."
        ),
        "excluded_events": sorted(EXCLUDE),
        "n_events": len(kept),
        "kept_events": kept,
        "bootstrap_ci_by_selector": by_selector,
        "effect_sizes_proposed_vs": effect_sizes,
    }
    dest = ROOT / "results" / "robustness_leave2out.json"
    dest.write_text(json.dumps(out, indent=2))
    print(f"wrote {dest}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
