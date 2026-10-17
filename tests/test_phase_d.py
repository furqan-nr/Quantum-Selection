"""Tests of the frozen Phase D analysis, runner plugin and backport generator on SYNTHETIC data only
(PREREGISTRATION_PHASE_D.md). No Qiskit and no study data are used."""
from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load_module("phase_d_analysis", REPO / "phase_d/analysis/phase_d_analysis.py")
PLUGIN = _load_module("phased_plugin", REPO / "phase_d/runner/phased_plugin.py")
MB = _load_module("make_backports", REPO / "phase_d/tools/make_backports.py")
CFG = json.loads((REPO / "phase_d/config/phase_d_config.json").read_text())


# ------------------------------------------------------------------------------------------------ helpers
def coast_reference(suite, cost, budget=math.inf):
    """Literal port of src/cart/selectors/coast.coast_selector's loop with key = file, no severity, ties by CI order."""
    pos = {t: i for i, t in enumerate(suite)}
    seen, chosen, spent, remaining = set(), [], 0.0, list(suite)
    while remaining:
        remaining.sort(key=lambda t: (A.file_of(t) in seen, cost[t], pos[t]))
        picked = next((t for t in remaining if spent + cost[t] <= budget), None)
        if picked is None:
            break
        chosen.append(picked)
        spent += cost[picked]
        seen.add(A.file_of(picked))
        remaining.remove(picked)
    return chosen


def run_json(tests: dict, cal: float = 0.25) -> dict:
    return {"tests": {t: {"outcome": o, "duration": d, "file": t.split("::")[0], "synthetic": None}
                      for t, (o, d) in tests.items()},
            "files": {}, "env": [{"calibration_median_s": cal}], "complete": True}


def make_study(tmp: Path, n_events: int = 8, cal_b: float = 0.25, flip: bool = False):
    """Synthetic study: per event, files a..d with cheap and expensive tests; the detecting backported test is cheap,
    lives in the last file (late in CI order) and is unseen in P."""
    data = tmp / "assembled"
    data.mkdir(parents=True)
    events = []
    rng = random.Random(1)
    for i in range(n_events):
        P, B, F = f"9.{i}.0", f"9.{i}.1", f"9.{i}.2"
        files = ["test/python/transpiler/test_a.py", "test/python/transpiler/test_b.py",
                 "test/python/transpiler/test_c.py", "test/python/transpiler/test_z.py"]
        ptests, btests = {}, {}
        collected = []
        for f in files:
            for j in range(6):
                tid = f"{f}::T::test_{j}"
                d = 0.001 * (1 + j) if j < 4 else 2.0 + rng.random()
                ptests[tid] = ("passed", d)
                btests[tid] = ("passed", d * (1.0 + 0.05 * rng.random()))
                collected.append(tid)
        bp_phys = f"{CFG['slice']['backport_dir']}/test_backport_e{i}.py::T::test_fix_1_0"
        other_bp = f"{CFG['slice']['backport_dir']}/test_backport_other.py::T::test_other"
        collected += [bp_phys, other_bp]
        outcome_b = "failed"
        btests[bp_phys] = (outcome_b, 0.002)
        btests[other_bp] = ("failed", 0.002)
        if flip and i % 2 == 0:                      # make the detecting test expensive for half the events
            btests[bp_phys] = (outcome_b, 5.0)
        for k in (1, 2):
            (data / f"run_w{B}_t{B}_pass{k}.json").write_text(json.dumps(run_json(btests, cal_b)))
        (data / f"run_w{P}_t{P}_pass1.json").write_text(json.dumps(run_json(ptests)))
        (data / f"collect_{B}.json").write_text(json.dumps({"collected": collected,
                                                             "meta": {"calibration_median_s": cal_b}}))
        (data / f"fcheck_E{i}.json").write_text(json.dumps({"pre_existing": None,
                                                            "backport": run_json({bp_phys: ("passed", 0.002)})}))
        events.append({"event_id": f"E{i}", "P": P, "B": B, "F": F,
                       "backport_file": f"phase_d/backports/test_backport_e{i}.py",
                       "logical_file": "test/python/transpiler/test_z.py"})
    ledger = tmp / "ledger.json"
    ledger.write_text(json.dumps({"events": events}))
    return data, ledger


def run_analysis(tmp: Path, data: Path, ledger: Path, out: str = "out.json", env=None, locks=None):
    cmd = [sys.executable, str(REPO / "phase_d/analysis/phase_d_analysis.py"), "--ledger", str(ledger),
           "--data", str(data), "--locks", str(locks or (tmp / "locks")), "--out", str(tmp / out)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads((tmp / out).read_text())


# ------------------------------------------------------------------------------------------------ unit tests
def test_coast_d_equals_reference_loop():
    rng = random.Random(7)
    for _ in range(60):
        n = rng.randint(1, 40)
        suite = [f"f{rng.randint(0, 5)}.py::T::t{i}" for i in range(n)]
        suite = list(dict.fromkeys(suite))
        cost = {t: rng.choice([0.0, 0.5, 1.0, rng.random() * 3]) for t in suite}
        for budget in (math.inf, 0.0, 1.0, 2.5, rng.random() * 10):
            assert A.coast_d(suite, cost, budget) == coast_reference(suite, cost, budget)


def test_estimator_rules_and_speed_factor():
    pdur = {"f1.py::a": 1.0, "f1.py::b": 3.0, "f1.py::c": 5.0, "f2.py::a": 10.0}
    suite = ["f1.py::a", "f1.py::new", "f2.py::new", "f3.py::new"]
    est, src = A.estimator(suite, pdur, 3, 1.0)
    assert src == {"f1.py::a": "seen", "f1.py::new": "file_median", "f2.py::new": "global_median",
                   "f3.py::new": "global_median"}
    assert est["f1.py::new"] == 3.0 and est["f2.py::new"] == 4.0          # global median of 1,3,5,10 = 4
    est2, _ = A.estimator(suite, pdur, 3, 2.0)
    assert est2["f1.py::a"] == 2.0
    e = A.Event({"event_id": "X", "P": "p", "B": "b", "F": "f"}, CFG, Path("."))
    sf = A.speed_factor(e, {"env": [{"calibration_median_s": 1.0}]}, {"meta": {"calibration_median_s": 1.1}}, [0.8, 1.25])
    assert sf["k_applied"] == 1.0
    sf = A.speed_factor(e, {"env": [{"calibration_median_s": 1.0}]}, {"meta": {"calibration_median_s": 1.5}}, [0.8, 1.25])
    assert sf["k_applied"] == 1.5


def test_apfdc_time_box_plan():
    order = ["a", "b", "c", "d"]
    real = {"a": 1.0, "b": 1.0, "c": 2.0, "d": 4.0}
    assert A.apfdc(order, real, {"c"}) == pytest.approx(1 - (2 + 1) / 8)
    assert A.apfdc(order, real, set()) == 0.0
    assert A.time_box(order, real, 4.0) == ["a", "b", "c"]
    assert A.time_box(order, real, 3.9) == ["a", "b"]
    assert A.plan_greedy(["d", "a", "c"], real, 3.0) == ["a", "c"]
    assert A.first_detection(order, real, {"c"}) == {"rank": 3, "cost_s": 4.0}


def test_statistics():
    w = A.wilcoxon_exact_greater([0.1 * (i + 1) for i in range(8)])
    assert w["p"] == pytest.approx(1 / 256) and w["min_achievable_p"] == pytest.approx(1 / 256)
    w = A.wilcoxon_exact_greater([0.1, 0.0, 0.0])
    assert w["n"] == 1 and w["p"] == 0.5
    w = A.wilcoxon_exact_greater([-0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    assert w["p"] == pytest.approx(2 / 256)                               # W+=35: sign vectors with W >= 35: 2
    s = A.sign_test_greater([1, 1, 1, -1, 0])
    assert (s["wins"], s["losses"], s["ties"]) == (3, 1, 1) and s["p"] == pytest.approx(5 / 16)
    h = A.holm({"H1": 0.01, "H2": 0.04}, 0.05)
    assert h["H1"]["reject"] and h["H2"]["reject"]
    h = A.holm({"H1": 0.03, "H2": 0.04}, 0.05)
    assert not h["H1"]["reject"] and not h["H2"]["reject"]
    m = A.mcnemar_exact_greater([1, 1, 1, 0], [0, 0, 1, 0])
    assert m["a_only"] == 2 and m["p"] == pytest.approx(0.25)
    assert A.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_build_suite_placement_and_other_backports():
    e = A.Event({"event_id": "E", "P": "p", "B": "b", "F": "f", "backport_file": "phase_d/backports/test_backport_e.py",
                 "logical_file": "test/python/transpiler/test_b.py"}, CFG, Path("."))
    bd = CFG["slice"]["backport_dir"]
    coll = ["test/python/transpiler/test_a.py::T::t1", "test/python/transpiler/test_b.py::T::test_a",
            "test/python/transpiler/test_b.py::T::test_m", "test/python/transpiler/test_b.py::U::test_a",
            "test/python/transpiler/test_c.py::T::t1",
            f"{bd}/test_backport_e.py::T::test_fix_1", f"{bd}/test_backport_e.py::T::test_aa_2",
            f"{bd}/test_backport_e.py::New::test_x", f"{bd}/test_backport_other.py::T::x"]
    order, key, bp = A.build_suite(e, coll)
    assert bp == {"test/python/transpiler/test_b.py::T::test_fix_1", "test/python/transpiler/test_b.py::T::test_aa_2",
                  "test/python/transpiler/test_b.py::New::test_x"}
    # class-alphabetical position inside B's class T; a class absent from B's file goes to the end of the file
    assert order == ["test/python/transpiler/test_a.py::T::t1", "test/python/transpiler/test_b.py::T::test_a",
                     "test/python/transpiler/test_b.py::T::test_aa_2", "test/python/transpiler/test_b.py::T::test_fix_1",
                     "test/python/transpiler/test_b.py::T::test_m", "test/python/transpiler/test_b.py::U::test_a",
                     "test/python/transpiler/test_b.py::New::test_x", "test/python/transpiler/test_c.py::T::t1"]
    assert A.order_file_rr(order)[:3] == ["test/python/transpiler/test_a.py::T::t1",
                                          "test/python/transpiler/test_b.py::T::test_a",
                                          "test/python/transpiler/test_c.py::T::t1"]
    alts = A.alt_default_orders(order, key, bp)
    assert alts["backport_at_file_end"][-4:-1] == ["test/python/transpiler/test_b.py::T::test_fix_1",
                                                   "test/python/transpiler/test_b.py::T::test_aa_2",
                                                   "test/python/transpiler/test_b.py::New::test_x"]
    assert alts["backport_at_file_start"][1] == "test/python/transpiler/test_b.py::T::test_fix_1"
    assert A.backport_collisions(e, coll) == []


def test_backport_before_first_class_test_and_collision():
    e = A.Event({"event_id": "E", "P": "p", "B": "b", "F": "f", "backport_file": "phase_d/backports/test_backport_e.py",
                 "logical_file": "test/python/compiler/test_t.py"}, CFG, Path("."))
    bd = CFG["slice"]["backport_dir"]
    coll = ["test/python/compiler/test_t.py::T::test_m", "test/python/compiler/test_t.py::T::test_z",
            "test/python/transpiler/test_a.py::T::t1", f"{bd}/test_backport_e.py::T::test_a_1",
            f"{bd}/test_backport_e.py::T::test_z"]
    order, key, bp = A.build_suite(e, coll)
    assert order[:2] == ["test/python/compiler/test_t.py::T::test_a_1", "test/python/compiler/test_t.py::T::test_m"]
    assert A.backport_collisions(e, coll) == ["test/python/compiler/test_t.py::T::test_z"]
    alts = A.alt_default_orders(order, key, bp)
    assert alts["transpiler_dir_first"][0] == "test/python/transpiler/test_a.py::T::t1"


def test_plugin_normalization():
    assert PLUGIN.normalize("f.py::T::test_1_x_object_at_0x772b46dca620__level0") == "f.py::T::test_1_x_object_at_0x?__level0"
    assert PLUGIN.normalize("f.py::T::test_<G at 0x7f00aa11bb22>") == "f.py::T::test_<G at 0x?>"
    assert PLUGIN.normalize("f.py::T::test_0x1f") == "f.py::T::test_0x1f"


def test_runner_units_put_backports_after_their_logical_file(monkeypatch):
    R = _load_module("run_phase_d", REPO / "phase_d/runner/run_phase_d.py")
    monkeypatch.setattr(R, "slice_files", lambda v: ["test/python/compiler/test_transpiler.py",
                                                     "test/python/transpiler/test_a.py",
                                                     "test/python/transpiler/test_optimize_1q_decomposition.py",
                                                     "test/python/transpiler/test_commutative_cancellation.py"])
    units = R.run_units("2.5.0")                                          # B of D4 and D7
    bd = CFG["slice"]["backport_dir"]
    assert ["test/python/transpiler/test_commutative_cancellation.py", f"{bd}/test_backport_d4.py"] in units
    assert ["test/python/transpiler/test_optimize_1q_decomposition.py", f"{bd}/test_backport_d7.py"] in units
    assert [u[0] for u in units] == sorted(u[0] for u in units)
    assert R.run_units("2.4.2") == [[f] for f in sorted(R.slice_files("2.4.2"))]   # P-only release: no backports


def test_backport_bindings_relative_import():
    src = "from .helpers import h\nimport ddt\nfrom qiskit import transpile as tp\nX = 1\ndef helper():\n    pass\n"
    b = MB._module_bindings(ast.parse(src), "test.python.transpiler")
    assert b["h"] == "from test.python.transpiler.helpers import h"
    assert b["ddt"] == "import ddt" and b["tp"] == "from qiskit import transpile as tp"
    assert b["X"] == "__upstream__" and b["helper"] == "__upstream__"


def test_frozen_backports_are_valid_python_and_verbatim_marked():
    ledger = json.loads((REPO / "phase_d/events/phase_d_events.json").read_text())
    assert len(ledger["events"]) == 8
    for ev in ledger["events"]:
        text = (REPO / ev["backport_file"]).read_text()
        ast.parse(text)
        assert ev["logical_file"] in text
        if ev["backport"]["kind"] == "upstream_method":
            assert "Method text below is verbatim" in text
            for m in ev["backport"]["methods"]:
                assert f"def {m}(" in text


# ------------------------------------------------------------------------------------------------ end to end
def test_end_to_end_decisions_and_determinism(tmp_path):
    data, ledger = make_study(tmp_path)
    out = run_analysis(tmp_path, data, ledger)
    ev = out["events"][0]
    assert ev["detection"]["n_detecting"] == 1 and ev["detection"]["n_detecting_pre_existing"] == 0
    assert ev["exploratory"]["backport_estimate_source"] == {"test/python/transpiler/test_z.py::T::test_fix_1_0": "file_median"}
    assert ev["suite_size"] == 25                                         # other event's backport excluded
    dec = out["decisions"]
    # cheap detecting test late in CI order: coast_d beats default and random on every event
    assert dec["H"]["H1"]["wilcoxon"]["p"] == pytest.approx(1 / 256) and dec["H"]["H1"]["supported"]
    assert dec["H"]["H2"]["supported"]
    assert dec["D1"]["tiers"]["0.05"]["counts"]["coast_d"] == 8
    assert dec["P1"]["supported"] and dec["P2"]["supported"]
    assert dec["roles"] == {"confirmatory": ["P1", "P2"], "forecast_checks": ["D1", "H"]}
    assert any("no budget lock" in d for d in out["deviations"])
    # determinism: identical output across runs and hash seeds
    env = dict(os.environ, PYTHONHASHSEED="123")
    out2 = run_analysis(tmp_path, data, ledger, out="out2.json", env=env)
    assert json.dumps(out, sort_keys=True) == json.dumps(out2, sort_keys=True)


def test_end_to_end_refutation_paths(tmp_path):
    # B machine 1.6x slower than P (speed factor applied), detecting test expensive on half of the events
    data, ledger = make_study(tmp_path, cal_b=0.4, flip=True)
    out = run_analysis(tmp_path, data, ledger)
    assert out["events"][0]["speed"]["k_applied"] == pytest.approx(1.6)
    assert out["decisions"]["P2"]["supported"] is False                   # estimates inflated 1.6x
    assert out["decisions"]["D1"]["tiers"]["0.05"]["counts"]["coast_d"] < 8


def test_lock_written_before_B_and_refused_after(tmp_path):
    data, ledger = make_study(tmp_path, n_events=1)
    # remove B passes so the lock is allowed
    hidden = []
    for p in data.glob("run_w9.0.1_t9.0.1_pass*.json"):
        q = p.with_suffix(".hidden")
        p.rename(q)
        hidden.append((q, p))
    cmd = [sys.executable, str(REPO / "phase_d/analysis/phase_d_analysis.py"), "--ledger", str(ledger),
           "--data", str(data), "--locks", str(tmp_path / "locks"), "--lock", "E0"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for q, p in hidden:
        q.rename(p)
    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert r2.returncode != 0 and "must precede" in (r2.stderr + r2.stdout)
    out = run_analysis(tmp_path, data, ledger)
    assert out["events"][0]["budget_lock_matches"] is True and not any("lock" in d for d in out["deviations"])


def test_detection_requires_all_B_passes_and_F_pass(tmp_path):
    data, ledger = make_study(tmp_path, n_events=1)
    bd = CFG["slice"]["backport_dir"]
    bp = f"{bd}/test_backport_e0.py::T::test_fix_1_0"
    p2 = data / "run_w9.0.1_t9.0.1_pass2.json"
    d = json.loads(p2.read_text())
    d["tests"][bp]["outcome"] = "passed"                                 # flaky on B -> not detecting
    p2.write_text(json.dumps(d))
    out = run_analysis(tmp_path, data, ledger)
    assert out["events"][0]["detection"]["n_detecting"] == 0
    assert out["events"][0]["policies"]["apfdc"]["coast_d"] == 0.0


def test_event_without_data_is_excluded_and_reported(tmp_path):
    data, ledger = make_study(tmp_path, n_events=3)
    (data / "collect_9.2.1.json").unlink()
    out = run_analysis(tmp_path, data, ledger)
    assert [e["event_id"] for e in out["excluded_events"]] == ["E2"]
    assert len(out["events"]) == 2 and any("E2: excluded" in d for d in out["deviations"])


def test_p1_p2_exclude_the_events_backported_tests(tmp_path):
    # a hanging backported test (60 s on B, priced at a millisecond file median) must not decide P1/P2
    data, ledger = make_study(tmp_path, n_events=2)
    bd = CFG["slice"]["backport_dir"]
    for k in (1, 2):
        p = data / f"run_w9.0.1_t9.0.1_pass{k}.json"
        d = json.loads(p.read_text())
        d["tests"][f"{bd}/test_backport_e0.py::T::test_fix_1_0"] = {"outcome": "timeout", "duration": 60.0,
                                                                     "file": bd, "synthetic": "timeout"}
        p.write_text(json.dumps(d))
    out = run_analysis(tmp_path, data, ledger)
    e0 = out["events"][0]
    t = e0["policies"]["tiers"]["0.05"]["coast_d"]
    assert t["spend_ratio_incl_backport"] > 2.0 and t["spend_ratio"] < 1.25
    assert abs(e0["suite_cost_rel_error"]) < 0.25 and e0["suite_cost_rel_error_incl_backport"] < -0.25
    assert out["decisions"]["P1"]["supported"] and out["decisions"]["P2"]["supported"]


def test_lock_refused_with_raw_B_runs_and_never_rewritten(tmp_path):
    data, ledger = make_study(tmp_path, n_events=1)
    for p in data.glob("run_w9.0.1_t9.0.1_pass*.json"):
        p.unlink()
    raw = data.parent / "runs" / "w9.0.1_t9.0.1" / "pass1" / "files"
    raw.mkdir(parents=True)
    (raw / "x.jsonl").write_text("{}\n")
    cmd = [sys.executable, str(REPO / "phase_d/analysis/phase_d_analysis.py"), "--ledger", str(ledger),
           "--data", str(data), "--locks", str(tmp_path / "locks"), "--lock", "E0"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode != 0 and "must precede" in (r.stderr + r.stdout)
    import shutil
    shutil.rmtree(data.parent / "runs")
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    lk = json.loads((tmp_path / "locks" / "E0.json").read_text())
    assert "locked_utc" in lk and lk["analysis_sha256"]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0     # identical: unchanged
    pr = data / "run_w9.0.0_t9.0.0_pass1.json"                                       # P data changed -> refused
    d = json.loads(pr.read_text())
    for v in d["tests"].values():
        v["duration"] *= 2
    pr.write_text(json.dumps(d))
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode != 0 and "never rewritten" in (r.stderr + r.stdout)


def test_runner_refuses_B_pass_without_lock(tmp_path, monkeypatch):
    R = _load_module("run_phase_d", REPO / "phase_d/runner/run_phase_d.py")
    assert R.missing_locks("2.5.0", tmp_path) == ["D4", "D7"]
    assert R.missing_locks("2.4.2", tmp_path) == []                                  # P-only release
    (tmp_path / "budget_lock").mkdir()
    for e in ("D4", "D7"):
        (tmp_path / "budget_lock" / f"{e}.json").write_text("{}")
    assert R.missing_locks("2.5.0", tmp_path) == []
    monkeypatch.setattr(R, "data_root", lambda a: tmp_path / "empty")
    called = []
    monkeypatch.setattr(R, "run_files", lambda *x, **k: called.append(1))
    ns = type("NS", (), {"version": "2.2.2", "wheel": None, "files": None, "data": None, "pass_": 1})()
    with pytest.raises(SystemExit, match="budget locks first"):
        R.cmd_run(ns)
    assert not called
