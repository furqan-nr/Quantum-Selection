"""Regenerate paper/figures/fig4_detection.png from the frozen evaluation output.

Source of truth: results/evaluation_costhet_frozen.json (`detection_curve` block: grid + by_source,
produced by `python -m cart.cli evaluate --split all --random-seeds 20` on the frozen costhet corpus).
Run from the repo root:

    python scripts/plot_detection_curve.py

Committed 2026-08-07 (Phase 1 Step 2) so the figure is regenerable from source, not a one-off plot.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_REPO_ROOT = Path(__file__).resolve().parents[1]

_STYLE = {
    "diversity_only": dict(color="#1b9e77", lw=2.0, ls="-"),
    "cheapest_first": dict(color="#7570b3", lw=1.6, ls="--"),
    "history_only": dict(color="#e6ab02", lw=1.3, ls=":"),
    "change_stage": dict(color="#a6761d", lw=1.3, ls="-."),
    "random": dict(color="#666666", lw=1.6, ls="-"),
    "proposed": dict(color="#d95f02", lw=2.4, ls="-"),
}
_LABELS = {
    "diversity_only": "diversity_only",
    "cheapest_first": "cheapest_first",
    "history_only": "history_only",
    "change_stage": "change_stage",
    "random": "random (20-seed median)",
    "proposed": "proposed (risk_score)",
}
_ORDER = ["cheapest_first", "history_only", "change_stage", "diversity_only", "random", "proposed"]


def plot(
    eval_path: Path = _REPO_ROOT / "results" / "evaluation_costhet_frozen.json",
    out_path: Path = _REPO_ROOT / "paper" / "figures" / "fig4_detection.png",
    source: str = "mutation",
) -> Path:
    d = json.loads(eval_path.read_text())
    dc = d["detection_curve"]
    grid = dc["grid"]
    bs = dc["by_source"][source]

    fig, ax = plt.subplots(figsize=(7.2, 4.15), dpi=150)
    ax.fill_between(grid, bs["random_band_min"], bs["random_band_max"], color="#999999", alpha=0.25,
                     label="_nolegend_", zorder=1)
    for name in _ORDER:
        ax.plot(grid, bs[name], label=_LABELS[name], **_STYLE[name],
                 zorder=3 if name == "proposed" else 2)

    for frac, tag in [(0.05, "pr"), (0.5, "nightly")]:
        ax.axvline(frac, color="#bbbbbb", lw=0.8, ls=":", zorder=0)
        ax.text(frac, 1.015, tag, ha="center", va="bottom", fontsize=8, color="#777777")

    ax.set_xlabel("Budget fraction of $T_{full}$")
    ax.set_ylabel("Mean detection rate (9 mutation events)")
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.25, lw=0.5)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    p = plot()
    print(f"wrote {p}")
