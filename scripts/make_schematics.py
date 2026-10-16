"""Draw schematic Figures 1-3 from code (no generative AI). Writes paper/figures/fig1_pipeline.png,
fig2_cohorts.png, fig3_riskscore.png. Run from repo root: python scripts/make_schematics.py"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / "paper" / "figures"
C = dict(blue=("#e8f0fb", "#4a7fc1"), green=("#e6f3e3", "#4c9a45"), red=("#fbe7e7", "#cc4b4b"),
         gray=("#eeeeee", "#8c8c8c"), yellow=("#fff4cc", "#d9a521"))


def box(ax, x, y, w, h, text, col="blue", fs=10, weight="normal"):
    fc, ec = C[col]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.6))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, weight=weight, wrap=True)


def arrow(ax, p, q, **kw):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=14, lw=1.5, color="#333333", **kw))


def fig1():
    fig, ax = plt.subplots(figsize=(8.4, 3.9), dpi=200); ax.set_xlim(0, 10); ax.set_ylim(0.2, 4.4); ax.axis("off")
    labels = ["Phase 0\nStatic manifest +\ninstrumentation", "Phase 1\nEvents: cohorts,\nmutation engine", "Phase 2\nGround truth:\ntiered oracles",
              "Phases 3-4\nBaselines +\nrisk_score selection", "Phase 5\nMetrics + 6\nvalidity gates"]
    xs = [0.1 + i * 2.0 for i in range(5)]
    for x, t in zip(xs, labels):
        box(ax, x, 2.5, 1.75, 1.6, t, "blue", 8.3)
        arrow(ax, (x + 0.875, 2.5), (x + 0.875, 1.55))
    for a, b in zip(xs[:-1], xs[1:]):
        arrow(ax, (a + 1.78, 3.3), (b - 0.03, 3.3))
    box(ax, 0.1, 0.45, 9.75, 1.05, "Reproducibility substrate: two-layer environment (pinned harness + per-event from-source Qiskit)\n"
        "write-once raw artifacts | CPU-time cost | frozen stage map | frozen budgets, labels isolated from selectors", "gray", 8.2)
    fig.savefig(OUT / "fig1_pipeline.png", bbox_inches="tight"); plt.close(fig)


def fig2():
    fig, ax = plt.subplots(figsize=(8.4, 4.4), dpi=200); ax.set_xlim(0, 10); ax.set_ylim(0, 5.2); ax.axis("off")
    ax.annotate("", xy=(9.6, 4.5), xytext=(1.6, 4.5), arrowprops=dict(arrowstyle="-|>", lw=2.2, color="black"))
    ax.text(9.7, 4.5, "time", va="center", fontsize=11)
    pts = {"c0": 2.0, "c1": 4.0, "c2": 6.0, "c3": 8.0}
    for k, x in pts.items():
        ax.plot([x], [4.5], "o", ms=9, color="black"); ax.text(x, 4.85, k, ha="center", fontsize=12)
    ax.text(0.1, 2.9, "forward_regression", color="#1a8a1a", fontsize=10.5, weight="bold", va="center")
    box(ax, 3.0, 2.55, 2.0, 0.7, "baseline (good)", "green", 9); box(ax, 5.0, 2.55, 2.0, 0.7, "candidate (buggy)", "red", 9)
    ax.plot([4.0, 4.0], [4.4, 3.3], ls=":", color="#1a8a1a", lw=2); ax.plot([6.0, 6.0], [4.4, 3.3], ls=":", color="#cc2222", lw=2)
    ax.text(7.4, 2.9, "introducing commit\nis the candidate", color="#555555", fontsize=10, va="center")
    ax.text(0.1, 1.0, "fix_boundary\n_differential", color="#1a4fb8", fontsize=10.5, weight="bold", va="center")
    box(ax, 3.3, 0.65, 3.0, 0.7, "candidate (buggy = fix parent)", "red", 8.8); box(ax, 6.5, 0.65, 2.3, 0.7, "baseline (good = fix)", "green", 8.8)
    ax.plot([6.0, 6.0], [2.5, 1.4], ls=":", color="#cc2222", lw=2); ax.plot([8.0, 8.0], [4.4, 1.4], ls=":", color="#1a8a1a", lw=2)
    ax.text(8.95, 1.0, "reverse\norientation:\nbaseline is\nthe fix", color="#555555", fontsize=9, va="center")
    fig.savefig(OUT / "fig2_cohorts.png", bbox_inches="tight"); plt.close(fig)


def fig3():
    fig, ax = plt.subplots(figsize=(8.4, 5.4), dpi=200); ax.set_xlim(0, 10.1); ax.set_ylim(0, 6.6); ax.axis("off")
    ax.text(0.1, 6.4, "severity and detectability are separate factors", style="italic", color="#666666", fontsize=10)
    items = [("epsilon + change_stage_match", "blue"), ("circuit_backend_sensitivity", "blue"), ("impact_prior (severity)", "green"),
             ("oracle_confidence (detectability)", "red"), ("÷ expected_cost (CPU time)", "gray"), ("novelty_multiplier", "blue")]
    for i, (t, c) in enumerate(items):
        y = 5.2 - i * 0.92
        box(ax, 0.1, y, 3.5, 0.7, t, c, 9)
        arrow(ax, (3.65, y + 0.35), (4.6, 3.1 + (i - 2.5) * 0.1))
    box(ax, 4.65, 2.7, 2.3, 0.9, "risk_score\n(interpretable)", "yellow", 10.5, "bold")
    box(ax, 7.5, 4.3, 2.5, 0.9, "greedy MAIN\nallocation (≤ budget)", "blue", 9)
    box(ax, 7.5, 1.1, 2.5, 0.9, "exploration RESERVE\n(10-20%, stage-indep.)", "green", 9)
    arrow(ax, (7.0, 3.35), (7.55, 4.5)); arrow(ax, (7.0, 2.95), (7.55, 1.8))
    fig.savefig(OUT / "fig3_riskscore.png", bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    fig1(); fig2(); fig3(); print("wrote figures")
