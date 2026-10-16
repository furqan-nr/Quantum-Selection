"""Regenerate Figs. 1-3 of the Software Quality Journal manuscript (paper/sqj/Fig1-3.{eps,png}).

Fig. 1: the cart pipeline schematic (same content as scripts/make_schematics.py fig1, vector output).
Fig. 2: mean detection-versus-budget curves on the 19 scale-up events (prioritisation view), from
        results/evaluation_scaleup_frozen.json -> detection_curve. The x axis is the budget as a fraction of
        each event's labeled full-suite cost (transpilation plus the oracle actually run), which is how
        cart.metrics.curves scores prefixes. Random ordering is the per-grid-point median over the 20 seeds of
        the frozen evaluation, with the 20-seed min-max band.
Fig. 3: real seconds spent relative to the frozen pr and nightly budgets on the 19 scale-up events, with the
        constant oracle estimates versus a leave-one-event-out cost estimate (results/revision_costscale.json).

All figures use black/grey line styles and hatching so they remain readable in black-and-white print, and
sans-serif lettering. Run from the repository root:  python scripts/plot_sqj_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "sqj"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "ps.fonttype": 42, "pdf.fonttype": 42})


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.eps", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.png", dpi=600, bbox_inches="tight")
    plt.close(fig)


def fig1():
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    ax.set_xlim(0, 10); ax.set_ylim(0.2, 4.4); ax.axis("off")
    labels = ["Phase 0\nStatic\nmanifest and\ninstrumentation", "Phase 1\nChange\nevents and\nmutations",
              "Phase 2\nGround truth\nwith tiered\noracles", "Phases 3-4\nBaselines\nand\nselectors",
              "Phase 5\nMetrics and\nsix validity\ngates"]
    w, h, y = 1.75, 1.75, 2.35
    xs = [0.2 + i * 1.95 for i in range(5)]
    for i, (x, t) in enumerate(zip(xs, labels)):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                    fc="white", ec="black", lw=1.2))
        ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=7, linespacing=1.3)
        if i < 4:
            ax.annotate("", xy=(xs[i + 1], y + h / 2), xytext=(x + w, y + h / 2),
                        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.2))
        ax.annotate("", xy=(x + w / 2, 1.75), xytext=(x + w / 2, y),
                    arrowprops=dict(arrowstyle="-|>", color="0.35", lw=1.0))
    ax.add_patch(FancyBboxPatch((0.2, 0.45), 9.55, 1.25, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc="0.92", ec="0.35", lw=1.0))
    ax.text(5.0, 1.07, "Reproducibility substrate: pinned harness + per-event from-source Qiskit builds\n"
                       "write-once raw artifacts | calibrated costs | frozen stage map | budgets frozen before labels",
            ha="center", va="center", fontsize=7)
    save(fig, "Fig1")


def fig2():
    d = json.loads((ROOT / "results" / "evaluation_scaleup_frozen.json").read_text())["detection_curve"]
    grid, bs = d["grid"], d["by_source"]["mutation"]
    fig, ax = plt.subplots(figsize=(7.0, 3.9))
    ax.fill_between(grid, bs["random_band_min"], bs["random_band_max"], color="0.85", lw=0, zorder=1,
                    label="Random, 20-seed range")
    styles = [("cheapest_first", "Cost-ordered baselines", dict(color="0.45", ls="--", lw=1.4, marker="s", markevery=6, ms=4)),
              ("diversity_only", "Diversity-only", dict(color="black", ls="-", lw=1.6, marker="o", markevery=(0, 7), ms=4, mfc="white")),
              ("decomposed", "Decomposed", dict(color="black", ls=":", lw=1.8, marker="^", markevery=(3, 7), ms=4)),
              ("random", "Random, 20-seed median", dict(color="0.55", ls="-.", lw=1.2)),
              ("proposed", "Composite (risk_score)", dict(color="black", ls="-", lw=2.6))]
    for key, lab, st in styles:
        ax.plot(grid, bs[key], label=lab, zorder=3, **st)
    for frac, tag in [(0.05, "pr"), (0.5, "nightly")]:
        ax.axvline(frac, color="0.6", lw=0.8, ls=":", zorder=0)
        ax.text(frac, 1.015, tag, ha="center", va="bottom", fontsize=8, color="0.3")
    ax.set_xlabel("Budget (fraction of the event's labeled full-suite cost)")
    ax.set_ylabel("Mean detection rate (19 events)")
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right", fontsize=7.5, framealpha=0.95)
    ax.grid(True, alpha=0.25, lw=0.5)
    save(fig, "Fig2")


def fig3():
    """Real (labeled) seconds spent relative to the FROZEN tier budgets on the 19 scale-up events, when the
    selectors budget with the constant oracle estimates versus a leave-one-event-out cost estimate
    (results/revision_costscale.json, s5_frozen_budgets, models "constant" and "loo_exact")."""
    c = json.loads((ROOT / "results" / "revision_costscale.json").read_text())["scaleup_19"]["s5_frozen_budgets"]
    sel = [("cheapest_first", "Cost-ordered\nbaselines"), ("diversity_only", "Diversity-only"), ("decomposed", "Decomposed"),
           ("random", "Random"), ("proposed", "Composite\n(risk_score)")]
    models = [("constant", "Constant oracle estimates", "0.3", ""), ("loo_exact", "Cross-event estimate", "0.85", "//")]
    fig, axs = plt.subplots(1, 2, figsize=(10.0, 3.6), sharey=True)
    for ax, tier in zip(axs, ("pr", "nightly")):
        w = 0.36
        for k, (m, lab, col, hatch) in enumerate(models):
            vals = [c[m][tier]["by_selector"][n]["mean_spent_over_budget"] for n, _ in sel]
            xs = [i + (k - 0.5) * w for i in range(len(sel))]
            ax.bar(xs, vals, w, color=col, edgecolor="black", hatch=hatch, linewidth=0.6, label=lab)
            for x0, v in zip(xs, vals):
                ax.text(x0, v * 1.15, f"{v:.1f}" if v < 10 else f"{v:.0f}", ha="center", va="bottom", fontsize=6.5)
        ax.axhline(1.0, color="black", ls="--", lw=1)
        ax.set_yscale("log"); ax.set_ylim(0.3, 600)
        ax.set_xticks(range(len(sel))); ax.set_xticklabels([s for _, s in sel], fontsize=8)
        budget = c["constant"][tier]["budget_s"]
        ax.set_title(f"{tier} tier (frozen budget {budget:.2f} s)", fontsize=9)
    axs[0].set_ylabel("Real seconds spent / frozen budget (log)")
    axs[1].legend(fontsize=7.5, frameon=False, loc="upper right")
    fig.tight_layout()
    save(fig, "Fig3")


if __name__ == "__main__":
    for f in (fig1, fig2, fig3):
        f()
    print("wrote", OUT / "Fig1-3.{eps,png}")
