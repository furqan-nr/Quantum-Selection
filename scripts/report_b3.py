#!/usr/bin/env python3
"""B3 reporting scaffolding — per-cohort selection tables from an evaluate.json report.

Consumes the schema emitted by `cart.metrics.evaluate.evaluate` (see results/phase5-*/evaluation.json):
top-level `by_source`, `per_event`, `win_tie_loss`, `effect_sizes`, `bootstrap_ci`, `random_multiseed`,
`detection_curve`. It renders, per cohort (never pooled), three Markdown tables ready for the manuscript:

  1. Detection-vs-budget: mean AUC + 95% bootstrap CI, recall@20%, mean normalized TTFR, overhead.
  2. Effect size of `proposed` vs each baseline: Cliff's delta, magnitude, Vargha-Delaney A12.
  3. Win / tie / loss of `proposed` vs each baseline.

LEAKAGE-SAFETY GATE (hard):
  Selection-comparison numbers are printed ONLY IF the corpus design is frozen
  (`configs/corpus_costhet.yaml` -> `frozen: true`) OR the report is MOCK/synthetic (`_mock: true`).
  On a REAL evaluation.json while the design is still `frozen: false`, this tool validates the schema and
  prints a SUPPRESSED banner with NO numbers. Test it on mock data with `--selftest`.

COHORTS: evaluate.py now groups by `evaluation_cohort` (forward_regression / fix_boundary / mutation), never
pooled (§1.4). A cohort with n < 3 events — the forward cohort is n=2 (H4 #14120 + #14904) — is reported PER
EVENT only: no bootstrap CI, no Cliff's δ, no aggregate win/tie/loss (the sample is too small to support them).
The mutation cohort (n=9) carries the aggregate comparison that is now the paper's headline.

Usage:
  python scripts/report_b3.py --selftest                 # render on MOCK data (always allowed)
  python scripts/report_b3.py --eval results/phase5-*/evaluation.json [--out report.md]
Standalone: stdlib only; does not import cart and never runs an evaluation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTOR_ORDER = ["proposed", "cheapest_first", "history_only", "change_stage", "diversity_only", "random"]
REQUIRED_TOP = ["by_source", "per_event", "win_tie_loss", "effect_sizes", "bootstrap_ci"]
# Cohorts smaller than this are reported PER EVENT only — no bootstrap CI, Cliff's delta, or aggregate
# win/tie/loss (the sample is too small to support them). The forward cohort is n=2 (H4 + #14904).
MIN_EVENTS_FOR_AGGREGATE = 3


# ---------------------------------------------------------------------------- frozen gate

def design_frozen(repo_root: Path = _REPO_ROOT) -> bool:
    """True only if configs/corpus_costhet.yaml has a top-level `frozen: true`."""
    cfg = repo_root / "configs" / "corpus_costhet.yaml"
    if not cfg.exists():
        return False
    for line in cfg.read_text().splitlines():
        if line and not line[0].isspace() and line.split(":", 1)[0].strip() == "frozen":
            return line.split(":", 1)[1].strip().lower().startswith("true")
    return False


def numbers_allowed(report: dict, repo_root: Path = _REPO_ROOT) -> bool:
    return report.get("_mock") is True or design_frozen(repo_root)


# ---------------------------------------------------------------------------- schema validation

def validate_schema(report: dict) -> list[str]:
    problems = [f"missing top-level key: {k}" for k in REQUIRED_TOP if k not in report]
    for src, sels in report.get("by_source", {}).items():
        if not isinstance(sels, dict):
            problems.append(f"by_source[{src}] is not an object")
            continue
        for sel, row in sels.items():
            if "mean_AUC_detection_vs_budget" not in row:
                problems.append(f"by_source[{src}][{sel}] missing mean_AUC_detection_vs_budget")
    return problems


# ---------------------------------------------------------------------------- rendering

def _fmt(x, nd=4):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "—"


def _ci(bootstrap_ci_src: dict, sel: str) -> str:
    by = (bootstrap_ci_src or {}).get("by_selector", {})
    d = by.get(sel)
    if not isinstance(d, dict) or "lo" not in d or "hi" not in d:
        return "—"
    return f"[{_fmt(d['lo'])}, {_fmt(d['hi'])}]"


def render_cohort(report: dict, source: str) -> str:
    """Dispatch: small cohorts (n < MIN_EVENTS_FOR_AGGREGATE) get a per-event table only."""
    sels = report["by_source"][source]
    present = [s for s in SELECTOR_ORDER if s in sels] + [s for s in sels if s not in SELECTOR_ORDER]
    n_events = next((sels[s].get("n_events") for s in present if "n_events" in sels[s]), None)
    if isinstance(n_events, int) and n_events < MIN_EVENTS_FOR_AGGREGATE:
        return _render_cohort_per_event(report, source, n_events)
    return _render_cohort_aggregate(report, source, present, n_events if n_events is not None else "?")


def _render_cohort_per_event(report: dict, source: str, n_events: int) -> str:
    """Per-event only (claim-scope rule for small cohorts): no CI, no Cliff's δ, no aggregate W/T/L."""
    pe = report.get("per_event", {}).get(source, {})
    out = [f"### Cohort: `{source}`  (n_events = {n_events} — per-event only)", "",
           f"> n < {MIN_EVENTS_FOR_AGGREGATE}: reported per event under the claim-scope rule — no bootstrap CI, "
           f"Cliff's δ, or aggregate win/tie/loss (sample too small to support them).", ""]
    if not pe:
        return "\n".join(out + ["_(no per-event records present)_", ""])
    events = list(pe.keys())
    present = [s for s in SELECTOR_ORDER if any(s in pe[e] for e in events)]
    out += ["**Per-event detection-vs-budget AUC (✓ detected / ✗ missed):**", "",
            "| event | " + " | ".join(present) + " |",
            "|---|" + "---|" * len(present)]
    for e in events:
        row = [f"`{e}`"]
        for s in present:
            cell = pe[e].get(s, {}) or {}
            auc = cell.get("AUC", cell.get("AUC_median"))
            det = cell.get("detected")
            mark = "✓" if det is True else ("✗" if det is False else "")
            row.append((f"{_fmt(auc)} {mark}".strip()) if auc is not None else "—")
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    return "\n".join(out)


def _render_cohort_aggregate(report: dict, source: str, present: list[str], n_events) -> str:
    sels = report["by_source"][source]
    bci = report.get("bootstrap_ci", {}).get(source, {})
    out = [f"### Cohort: `{source}`  (n_events = {n_events})", ""]
    # 1) detection-vs-budget
    out += ["**Detection-vs-budget (mean over events):**", "",
            "| selector | mean AUC | 95% CI (AUC) | recall@20% | mean nTTFR | overhead s |",
            "|---|---|---|---|---|---|"]
    for s in present:
        r = sels[s]
        out.append("| {}{} | {} | {} | {} | {} | {} |".format(
            s, " *(proposed)*" if s == "proposed" else "",
            _fmt(r.get("mean_AUC_detection_vs_budget")), _ci(bci, s),
            _fmt(r.get("recall@20%")), _fmt(r.get("mean_normalized_TTFR")),
            _fmt(r.get("mean_selection_overhead_s"), 4)))
    # 2) effect sizes vs proposed
    es = report.get("effect_sizes", {}).get(source, {}).get("proposed_vs", {})
    if es:
        out += ["", "**Effect size of `proposed` vs each baseline (metric = AUC):**", "",
                "| baseline | Cliff's δ | magnitude | A12 |", "|---|---|---|---|"]
        for s in present:
            if s in es:
                e = es[s]
                out.append(f"| {s} | {_fmt(e.get('cliffs_delta'))} | {e.get('magnitude','—')} | {_fmt(e.get('a12'))} |")
    # 3) win/tie/loss
    wtl = report.get("win_tie_loss", {}).get(source, {})
    if wtl:
        out += ["", "**Win / tie / loss (`proposed` vs each baseline):**", "",
                "| baseline | win | tie | loss |", "|---|---|---|---|"]
        for s in present:
            if s in wtl:
                w = wtl[s]
                out.append(f"| {s} | {w.get('win','—')} | {w.get('tie','—')} | {w.get('loss','—')} |")
    out.append("")
    return "\n".join(out)


def render_report(report: dict) -> str:
    head = ["# B3 — Selection results (per cohort, never pooled)", ""]
    if report.get("_mock"):
        head += ["> **MOCK / SYNTHETIC DATA** — illustrates the table format only; not a real result.", ""]
    head.append(f"Split: `{report.get('split','?')}` · random seeds: {report.get('random_seeds','?')} · "
                f"oracle FP rate: {_fmt(report.get('oracle_false_positive_rate'))}")
    head.append("")
    body = [render_cohort(report, src) for src in report.get("by_source", {})]
    return "\n".join(head + body)


# ---------------------------------------------------------------------------- mock data

def mock_report() -> dict:
    """Synthetic report in the evaluate.json shape — mutation (n=5, aggregate) + forward (n=2, per-event)."""
    def cohort(auc, n):
        sels = {}
        for s, a in auc.items():
            sels[s] = {"n_events": n, "recall@20%": round(a, 4), "mean_normalized_TTFR": round(1 - a, 4),
                       "mean_AUC_detection_vs_budget": a, "detection_at_fraction": {"20%": round(a, 4)},
                       "mean_selection_overhead_s": 0.001}
        sels["random"]["n_seeds"] = 20
        return sels

    def pe_event(base_auc):
        row = {s: {"detected": True, "AUC": round(base_auc, 4), "normalized_TTFR": round(1 - base_auc, 4),
                   "recall@20%": 1} for s in SELECTOR_ORDER if s != "random"}
        row["random"] = {"detected": True, "AUC_median": round(base_auc - 0.05, 4),
                         "normalized_TTFR_median": round(1 - base_auc + 0.05, 4)}
        return row

    mut = {"proposed": 0.71, "cheapest_first": 0.80, "history_only": 0.80,
           "change_stage": 0.80, "diversity_only": 0.82, "random": 0.74}
    fwd = {"proposed": 0.88, "cheapest_first": 0.55, "history_only": 0.60,
           "change_stage": 0.72, "diversity_only": 0.58, "random": 0.61}

    def es(auc):
        return {"metric": "AUC_detection_vs_budget", "n_events": 5,
                "proposed_vs": {s: {"cliffs_delta": round(auc["proposed"] - v, 3),
                                    "magnitude": "small", "a12": round(0.5 + (auc["proposed"] - v) / 2, 3)}
                                for s, v in auc.items() if s != "proposed"}}

    def bci(auc):
        return {"metric": "AUC_detection_vs_budget",
                "by_selector": {s: {"mean": v, "lo": round(max(0, v - 0.2), 4), "hi": round(min(1, v + 0.1), 4)}
                                for s, v in auc.items()}}

    def wtl(auc):
        return {s: {"win": 3, "tie": 1, "loss": 1} for s in auc if s != "proposed"}

    return {"_mock": True, "split": "all", "random_seeds": 20, "oracle_false_positive_rate": 0.0678,
            "by_source": {"mutation": cohort(mut, 5), "forward_regression": cohort(fwd, 2)},
            # forward cohort (n=2) carries per-event rows and NO aggregate stats — the renderer enforces this
            "per_event": {"mutation": {}, "forward_regression": {
                "hist-vf2postlayout-noop": pe_event(0.93),
                "fwd-applylayout-registers-14904": pe_event(0.85)}},
            "win_tie_loss": {"mutation": wtl(mut)},
            "effect_sizes": {"mutation": es(mut)},
            "bootstrap_ci": {"mutation": bci(mut)}}


# ---------------------------------------------------------------------------- main

def _suppressed_banner(problems: list[str]) -> str:
    ok = "schema OK" if not problems else f"schema issues: {problems}"
    return ("=" * 64 + "\n"
            " B3 REPORT — SUPPRESSED\n"
            " configs/corpus_costhet.yaml is `frozen: false`.\n"
            " Selection-comparison numbers are withheld until the design is\n"
            " frozen on the parent (leakage-safety). No numbers were computed.\n"
            f" ({ok}; run `--selftest` to see the format on mock data.)\n"
            + "=" * 64)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B3 per-cohort selection reporting (frozen-gated).")
    ap.add_argument("--eval", help="path to a real evaluation.json")
    ap.add_argument("--selftest", action="store_true", help="render on MOCK data (always allowed)")
    ap.add_argument("--out", help="write the Markdown report to this path")
    ap.add_argument("--repo-root", default=str(_REPO_ROOT))
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root)

    if args.selftest:
        rep = mock_report()
        problems = validate_schema(rep)
        print(f"[selftest] mock schema validation: {'OK' if not problems else problems}", file=sys.stderr)
        print(f"[selftest] design_frozen={design_frozen(repo_root)}  numbers_allowed(mock)={numbers_allowed(rep, repo_root)}",
              file=sys.stderr)
        md = render_report(rep)
        # Gate demonstration: a REAL-shaped report (no _mock) is suppressed while frozen:false.
        realish = {k: v for k, v in rep.items() if k != "_mock"}
        print(f"[selftest] gate on real-shaped report while frozen=false -> numbers_allowed="
              f"{numbers_allowed(realish, repo_root)} (expect False unless frozen)", file=sys.stderr)
        if args.out:
            Path(args.out).write_text(md)
            print(f"[selftest] wrote {args.out}", file=sys.stderr)
        print(md)
        return 0

    if not args.eval:
        ap.error("provide --eval PATH or --selftest")
    report = json.loads(Path(args.eval).read_text())
    problems = validate_schema(report)
    if not numbers_allowed(report, repo_root):
        print(_suppressed_banner(problems))
        return 0
    if problems:
        print(f"schema issues: {problems}", file=sys.stderr)
    md = render_report(report)
    if args.out:
        Path(args.out).write_text(md)
        print(f"wrote {args.out}", file=sys.stderr)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
