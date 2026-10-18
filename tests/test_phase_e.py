"""Tests of the frozen Phase E analysis, runner gate, configuration and estimator-selection record
(PREREGISTRATION_PHASE_E.md). Synthetic data only, plus (where present) Phase D development data. No Phase E study
release is read or executed."""
from __future__ import annotations

import ast
import importlib.util
import json
import math
import random
import re
import statistics
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E = _load_module("phase_e_analysis", REPO / "phase_e/analysis/phase_e_analysis.py")
D = _load_module("phase_d_analysis_for_e", REPO / "phase_d/analysis/phase_d_analysis.py")
RUN = _load_module("run_phase_e", REPO / "phase_e/runner/run_phase_e.py")
CFG = json.loads((REPO / "phase_e/config/phase_e_config.json").read_text())
LEDGER = json.loads((REPO / "phase_e/events/phase_e_pairs.json").read_text())
SEL = json.loads((REPO / "phase_e/dev/estimator_selection.json").read_text())
PYPI = json.loads((REPO / "phase_e/tools/pypi_release_list.json").read_text())["releases"]
CHECKS = json.loads((REPO / "phase_e/tools/release_checks.json").read_text())["checks"]


# ------------------------------------------------------------------------------------------------ estimator
def test_quantile_type7_matches_statistics_inclusive():
    rng = random.Random(1)
    for n in (2, 3, 7, 50):
        xs = [rng.lognormvariate(0, 2) for _ in range(n)]
        qs = statistics.quantiles(xs, n=100, method="inclusive")
        for q in (0.25, 0.5, 0.9, 0.99):
            assert E.quantile(xs, q) == pytest.approx(qs[round(q * 100) - 1], rel=1e-12)
    assert E.quantile([5.0], 0.99) == 5.0


def _toy():
    pdur = {"a.py::T::t1": 1.0, "a.py::T::t2": 2.0, "a.py::T::t3": 9.0, "b.py::T::t1": 0.5, "b.py::T::t2": 0.7}
    suite = ["a.py::T::t1", "a.py::T::new", "b.py::T::t1", "b.py::T::new", "c.py::T::x", "c.py::T::y"]
    return pdur, suite


def test_estimator_sources_and_rules():
    pdur, suite = _toy()
    spec = CFG["estimators"]["primary"]["spec"]
    est, src = E.estimator(suite, pdur, spec)
    assert src == {"a.py::T::t1": "seen", "a.py::T::new": "in_file", "b.py::T::t1": "seen", "b.py::T::new": "new_file",
                   "c.py::T::x": "new_file", "c.py::T::y": "new_file"}
    assert est["a.py::T::t1"] == 1.0
    assert est["a.py::T::new"] == pytest.approx(4.0)                  # file mean of a.py
    p99 = E.quantile(list(pdur.values()), 0.99)
    assert est["b.py::T::new"] == pytest.approx(p99)                  # b.py has only 2 seen tests (< min_seen 3)
    assert est["c.py::T::x"] == pytest.approx(p99)
    est2, _ = E.estimator(suite, pdur, spec, k=2.0)
    assert all(est2[t] == pytest.approx(2 * est[t]) for t in suite)


def test_estimator_variants():
    pdur, suite = _toy()
    base = {"min_seen": 3, "in_file": {"stat": "median"}, "new_file": {"stat": "median", "over": "tests"}}
    est, _ = E.estimator(suite, pdur, base)
    assert est["a.py::T::new"] == 2.0 and est["c.py::T::x"] == 1.0
    est, _ = E.estimator(suite, pdur, {**base, "scale": 3.0})
    assert est["a.py::T::new"] == 6.0 and est["a.py::T::t1"] == 1.0  # scale applies to unseen prices only
    est, _ = E.estimator(suite, pdur, {**base, "in_file": {"stat": "mean", "shrink_kappa": 3}})
    gm = sum(pdur.values()) / 5
    assert est["a.py::T::new"] == pytest.approx((3 * 4.0 + 3 * gm) / 6)
    est, _ = E.estimator(suite, pdur, {**base, "in_file": {"stat": "median", "floor_global": True}})
    assert est["a.py::T::new"] == 2.0
    est, _ = E.estimator(suite, pdur, {**base, "new_file": {"stat": "mean", "over": "file_means"}})
    assert est["c.py::T::x"] == pytest.approx((4.0 + 0.6) / 2)
    est, src = E.estimator(suite, pdur, {**base, "min_seen": 2})
    assert src["b.py::T::new"] == "in_file" and est["b.py::T::new"] == pytest.approx(0.6)


def test_phase_d_registered_comparator_matches_phase_d_estimator():
    rng = random.Random(3)
    pdur = {f"f{i % 7}.py::T::t{i}": rng.lognormvariate(-5, 2) for i in range(200)}
    suite = list(pdur)[:150] + [f"f{i}.py::T::new{j}" for i in range(9) for j in range(3)]
    e_e, _ = E.estimator(suite, pdur, CFG["estimators"]["comparator_phase_d_registered"]["spec"])
    e_d, _ = D.estimator(suite, pdur, 3, 1.0)
    assert all(e_e[t] == pytest.approx(e_d[t], rel=1e-12) for t in suite)


def test_coast_d_identical_to_phase_d():
    rng = random.Random(5)
    for _ in range(20):
        suite = [f"f{rng.randrange(6)}.py::T::t{i}" for i in range(60)]
        suite = list(dict.fromkeys(suite))
        cost = {t: rng.choice([0.001, 0.01, 0.1, 1.0]) * rng.random() for t in suite}
        b = sum(cost.values()) * rng.choice([0.05, 0.25, 0.5])
        assert E.coast_d(suite, cost, b) == D.coast_d(suite, cost, b)
        assert E.plan_greedy(E.order_cheapest(suite, cost), cost, b) == D.plan_greedy(D.order_cheapest(suite, cost), cost, b)


def test_evaluate_estimator_charges_every_planned_test():
    pdur, suite = _toy()
    real = {t: 1.0 for t in suite}
    out = E.evaluate_estimator(suite, pdur, real, CFG["estimators"]["primary"]["spec"], 1.0, [0.25, 1.0])
    est, src = E.estimator(suite, pdur, CFG["estimators"]["primary"]["spec"])
    tot = sum(est.values())
    assert out["suite_cost_rel_error"] == pytest.approx(tot / 6 - 1, abs=1e-6)
    t = out["tiers"]["1.0"]["cheapest_first"]
    assert t["selected"] == 6 and t["spend_ratio"] == pytest.approx(6 / tot, abs=1e-6)
    assert t["spend_ratio_seen_part"] + t["spend_ratio_unseen_part"] == pytest.approx(t["spend_ratio"], abs=2e-6)


# ------------------------------------------------------------------------------------------------ decision rules
def _rows(ratios, errs):
    return [{"suite_cost_rel_error": e, "tiers": {str(f): {p: {"spend_ratio": r} for p in ("cheapest_first", "coast_d")}
                                                  for f in (0.05, 0.25)}} for r, e in zip(ratios, errs)]


def test_p1prime_is_per_pair():
    rule = CFG["confirmatory"]["P1prime"]
    assert rule["single_pair_spend_ratio_max"] == 1.25 and rule["mean_spend_ratio_max"] == 1.25
    assert E.decide_p1(_rows([1.0] * 9 + [1.25], [0] * 10), rule)["supported"]
    assert not E.decide_p1(_rows([0.5] * 9 + [1.2501], [0] * 10), rule)["supported"]   # mean 0.575 but one pair over
    cont = {**rule, **CFG["confirmatory"]["continuity_checks"]["P1_phase_d_thresholds"]}
    assert E.decide_p1(_rows([1.0] * 9 + [1.9], [0] * 10), cont)["supported"]
    assert E.p1_risk(E.decide_p1(_rows([1.0] * 9 + [1.5], [0] * 10), rule), rule) == pytest.approx(1.2)


def test_p2prime_boundaries():
    rule = CFG["confirmatory"]["P2prime"]
    ok = E.decide_p2([0.01] * 8 + [2.0, -0.9], rule)
    assert ok["supported"] and ok["share_within_band"] == 0.8 and not ok["strict_every_pair_within_band"]
    assert not E.decide_p2([0.01] * 7 + [2.0, -0.9, 0.26], rule)["supported"]          # 70% within band
    assert E.decide_p2([0.15] * 5 + [0.0] * 3 + [0.25, -0.25], rule)["supported"]       # median exactly 0.15
    assert not E.decide_p2([0.16] * 6 + [0.0] * 4, rule)["supported"]                   # median 0.16
    assert E.decide_p2([0.25, -0.25], rule)["strict_every_pair_within_band"]


# ------------------------------------------------------------------------------------------------ config / ledger
def test_pairs_fresh_disjoint_and_follow_the_p_rule():
    used = set(CFG["releases_used_in_phase_d_any_role"])
    for v in ("2.0.1", "2.0.2", "2.0.3", "2.1.0", "2.1.2", "2.2.0rc1", "2.2.1", "2.2.2", "2.2.3", "2.4.2", "2.5.0",
              "2.5.1", "2.5.2", "2.3.0", "2.3.1"):
        assert v in used
    vs = [v for e in LEDGER["events"] for v in (e["P"], e["B"])]
    assert len(vs) == len(set(vs)) == 20 and not (set(vs) & used)
    final = re.compile(r"^\d+\.\d+\.\d+$")
    for e in LEDGER["events"]:
        P, B = e["P"], e["B"]
        cands = [v for v, r in PYPI.items() if final.match(v) and not r["yanked"] and v.split(".")[0] == B.split(".")[0]
                 and r["upload_time_utc"] < PYPI[B]["upload_time_utc"]]
        assert P == max(cands, key=lambda v: PYPI[v]["upload_time_utc"]), e
        assert e["kind"] == ("patch" if P.split(".")[:2] == B.split(".")[:2] else "minor")
    assert sum(e["kind"] == "minor" for e in LEDGER["events"]) == 3
    assert all(r["ok"] for r in [{"ok": c} for c in E.leakage_checks(LEDGER, CFG)[-1].values()])
    assert all(x["fresh"] and x["P_uploaded_before_B"] for x in E.leakage_checks(LEDGER, CFG)[:-1])


def test_release_checks_cover_every_study_release():
    for v, info in CFG["versions"].items():
        c = CHECKS[v]
        assert not c["yanked"] and c["sdist_sha256_ok"] and c["pip_resolution"]["rc"] == 0
        assert c["sdist_test_tree"]["has_transpiler_dir"] and c["sdist_test_tree"]["has_compiler_dir"]
        assert info["wheel"] == c["wheel"] and info["sdist"] == c["sdist"]
        assert c["pip_resolution"]["qiskit_artifact"] == info["wheel"]["filename"]


def test_selection_record_matches_config():
    assert SEL["primary"]["spec"] == CFG["estimators"]["primary"]["spec"]
    assert SEL["secondary"]["spec"] == CFG["estimators"]["secondary"]["spec"]
    assert SEL["ranking_lopo"][0]["family"] == SEL["primary"]["family"]
    assert SEL["ranking_lopo"][1]["family"] == SEL["secondary"]["family"]
    r = SEL["rules"]
    c = CFG["confirmatory"]
    assert r["P1prime"]["single_pair_spend_ratio_max"] == c["P1prime"]["single_pair_spend_ratio_max"]
    assert r["P1prime"]["mean_spend_ratio_max"] == c["P1prime"]["mean_spend_ratio_max"]
    assert {k: r["P2prime"][k] for k in r["P2prime"]} == {k: c["P2prime"][k] for k in r["P2prime"]}


def test_plugin_and_calibration_identical_to_phase_d():
    def strip(p):
        t = ast.parse(Path(p).read_text())
        if t.body and isinstance(t.body[0], ast.Expr) and isinstance(t.body[0].value, ast.Constant):
            t.body = t.body[1:]
        return ast.dump(t)
    assert strip(REPO / "phase_e/runner/phasee_plugin.py") == strip(REPO / "phase_d/runner/phased_plugin.py")
    assert strip(REPO / "phase_e/runner/calibrate.py") == strip(REPO / "phase_d/runner/calibrate.py")
    assert "phasee_plugin" in CFG["environment"]["pytest_args"]


@pytest.mark.skipif(not (REPO / "phase_d/data/assembled/run_w2.2.1_t2.2.1_pass1.json").exists(), reason="no dev data")
def test_dev_numbers_reproduce_for_one_pair():
    sel = _load_module("select_estimator", REPO / "phase_e/dev/select_estimator.py")
    r = sel.row("2.2.1", "2.2.2", CFG["estimators"]["primary"]["spec"])
    stored = SEL["families"][SEL["primary"]["family"]]["lopo"]["heldout_per_pair"]["2.2.1->2.2.2"]
    assert r["tiers"]["0.05"]["cheapest_first"]["spend_ratio"] == pytest.approx(stored["cheapest_first@0.05"], abs=1e-6)
    assert r["suite_cost_rel_error"] == pytest.approx(stored["rel_error"], abs=1e-6)


# ------------------------------------------------------------------------------------------------ runner gate
def _write_locks(root: Path):
    ld = root / "budget_lock"
    ld.mkdir(parents=True, exist_ok=True)
    for e in LEDGER["events"]:
        (ld / f"{e['event_id']}.json").write_text(json.dumps({"event_id": e["event_id"]}))
    return ld


def test_runner_lock_gate(tmp_path):
    assert any("LOCK_PUSHED" in w for w in RUN.lock_gate("1.0.1", tmp_path))
    ld = _write_locks(tmp_path)
    assert RUN.lock_gate("1.0.1", tmp_path) == ["budget_lock/LOCK_PUSHED.json missing (run confirm-lock-push after the user has pushed the locks)"]
    with pytest.raises(SystemExit):
        RUN.cmd_confirm_lock_push(Namespace(data=str(tmp_path), commit="abc"))       # SHA too short
    RUN.cmd_confirm_lock_push(Namespace(data=str(tmp_path), commit="abc1234"))
    assert RUN.lock_gate("1.0.1", tmp_path) == []
    with pytest.raises(SystemExit):
        RUN.cmd_confirm_lock_push(Namespace(data=str(tmp_path), commit="abc1234"))   # never rewritten
    (ld / "E3.json").write_text("{}")
    assert any("E3.json changed" in w for w in RUN.lock_gate("1.0.1", tmp_path))


def test_runner_refuses_study_release_with_dryrun_options(tmp_path):
    with pytest.raises(SystemExit, match="--data"):
        RUN.cmd_run(Namespace(version="1.0.0", pass_=1, files=None, data=str(tmp_path)))
    with pytest.raises(SystemExit, match="not a Phase E study release"):
        RUN.cmd_run(Namespace(version="2.2.3", pass_=1, files=None, data=None))
    with pytest.raises(SystemExit, match="refused"):
        RUN.cmd_run(Namespace(version="2.4.1", pass_=1, files=None, data=None))


# ------------------------------------------------------------------------------------------------ end to end (synthetic)
def _synthetic_study(tmp: Path, n_pairs: int = 10, seed: int = 11, drift: float = 1.0, broken_files: int = 0):
    rng = random.Random(seed)
    data = tmp / "data" / "assembled"
    data.mkdir(parents=True)
    cfg = json.loads(json.dumps(CFG))
    cfg["versions"] = {}
    events = []
    for i in range(n_pairs):
        P, B = f"9.{i}.0", f"9.{i}.1"
        cfg["versions"][P] = {"upload_time_utc": f"2030-01-{i + 1:02d}T00:00:00"}
        cfg["versions"][B] = {"upload_time_utc": f"2030-01-{i + 1:02d}T12:00:00"}
        events.append({"event_id": f"E{i + 1}", "P": P, "B": B, "kind": "patch"})
        files = [f"test/python/transpiler/test_f{j}.py" for j in range(8)]
        ptests = {f"{f}::T::t{k}": rng.lognormvariate(-6, 1.5) for f in files[:7] for k in range(30)}
        btests = dict(ptests)
        for k in range(5):
            btests[f"{files[0]}::T::new{k}"] = rng.lognormvariate(-6, 1.5)
            btests[f"{files[7]}::T::n{k}"] = rng.lognormvariate(-4, 1)
        (data / f"run_w{P}_t{P}_pass1.json").write_text(json.dumps(
            {"complete": True, "env": [{"calibration_median_s": 0.2}], "files": {f: {"complete": True} for f in files[:7]},
             "tests": {t: {"outcome": "passed", "duration": d, "file": t.split("::")[0]} for t, d in ptests.items()}}))
        bfiles = files + [f"test/python/transpiler/test_broken{j}.py" for j in range(broken_files)]
        (data / f"collect_{B}.json").write_text(json.dumps({"collected": list(btests),
                                                            "meta": {"calibration_median_s": 0.21, "files": bfiles}}))
        for k in (1, 2):
            (data / f"run_w{B}_t{B}_pass{k}.json").write_text(json.dumps(
                {"complete": True, "env": [], "tests": {t: {"outcome": "passed", "duration": d * drift * rng.uniform(0.9, 1.1),
                                                            "file": t.split("::")[0]} for t, d in btests.items()}}))
    cfgp, ledp = tmp / "cfg.json", tmp / "ledger.json"
    cfgp.write_text(json.dumps(cfg))
    ledp.write_text(json.dumps({"events": events}))
    return cfgp, ledp, data, tmp / "data" / "budget_lock", events


def _main(cfgp, ledp, data, locks, out, *extra):
    return subprocess.run([sys.executable, str(REPO / "phase_e/analysis/phase_e_analysis.py"), "--config", str(cfgp),
                           "--ledger", str(ledp), "--data", str(data), "--locks", str(locks), "--out", str(out), *extra],
                          capture_output=True, text=True)


def test_end_to_end_lock_then_analysis(tmp_path):
    cfgp, ledp, data, locks, events = _synthetic_study(tmp_path)
    # B timing data exist -> lock refused; move them away, lock, put them back
    r = _main(cfgp, ledp, data, locks, tmp_path / "o.json", "--lock", "E1")
    assert r.returncode != 0 and "already exist" in (r.stderr + r.stdout)
    hold = tmp_path / "hold"
    hold.mkdir()
    for p in data.glob("run_w9.*.1_t*_pass*.json"):
        p.rename(hold / p.name)
    r = _main(cfgp, ledp, data, locks, tmp_path / "o.json", "--lock", *[e["event_id"] for e in events])
    assert r.returncode == 0, r.stderr
    lk = json.loads((locks / "E1.json").read_text())
    assert set(lk["estimators"]) == {"primary", "secondary", "phase_d_registered"} and lk["p_run_complete"]
    raw = data.parent / "runs" / "w9.0.1_t9.0.1" / "pass1"
    raw.mkdir(parents=True)
    (raw / "x").write_text("x")
    r = _main(cfgp, ledp, data, locks, tmp_path / "o.json", "--lock", "E1")
    assert r.returncode != 0 and "raw" in (r.stderr + r.stdout)
    for p in hold.glob("*.json"):
        p.rename(data / p.name)
    out = tmp_path / "o.json"
    r = _main(cfgp, ledp, data, locks, out)
    assert r.returncode == 0, r.stderr
    res = json.loads(out.read_text())
    assert all(p["budget_lock_matches"] for p in res["pairs"]) and res["deviations"] == []
    dec = res["decisions"]
    assert isinstance(dec["P1prime_supported"], bool) and isinstance(dec["P2prime_supported"], bool)
    # independent recomputation of one pair's primary numbers
    p = res["pairs"][0]
    prun = json.loads((data / "run_w9.0.0_t9.0.0_pass1.json").read_text())
    col = json.loads((data / "collect_9.0.1.json").read_text())["collected"]
    b = [json.loads((data / f"run_w9.0.1_t9.0.1_pass{k}.json").read_text())["tests"] for k in (1, 2)]
    real = {t: (b[0][t]["duration"] + b[1][t]["duration"]) / 2 for t in col}
    pdur = {t: v["duration"] for t, v in prun["tests"].items()}
    est, _ = E.estimator(col, pdur, CFG["estimators"]["primary"]["spec"])
    tot = math.fsum(est.values())
    assert p["estimators"]["primary"]["suite_cost_rel_error"] == pytest.approx(tot / math.fsum(real.values()) - 1, abs=1e-6)
    plan = E.plan_greedy(E.order_cheapest(col, est), est, 0.05 * tot)
    assert p["estimators"]["primary"]["tiers"]["0.05"]["cheapest_first"]["spend_ratio"] == pytest.approx(
        math.fsum(real[t] for t in plan) / (0.05 * tot), abs=1e-6)


def test_lock_never_rewritten_and_min_pairs(tmp_path):
    cfgp, ledp, data, locks, events = _synthetic_study(tmp_path, n_pairs=7)
    hold = tmp_path / "hold"
    hold.mkdir()
    for p in data.glob("run_w9.*.1_t*_pass*.json"):
        p.rename(hold / p.name)
    assert _main(cfgp, ledp, data, locks, tmp_path / "o.json", "--lock", "E1").returncode == 0
    lk = locks / "E1.json"
    rec = json.loads(lk.read_text())
    rec["estimators"]["primary"]["total_est_s"] = 1.0
    lk.write_text(json.dumps(rec))
    r = _main(cfgp, ledp, data, locks, tmp_path / "o.json", "--lock", "E1")
    assert r.returncode != 0 and "never rewritten" in (r.stderr + r.stdout)
    for p in hold.glob("*.json"):
        p.rename(data / p.name)
    out = tmp_path / "o.json"
    assert _main(cfgp, ledp, data, locks, out).returncode == 0
    res = json.loads(out.read_text())
    assert res["decisions"]["P1prime_supported"] is None                 # 7 < min_analysable_pairs = 8
    assert any("budget lock mismatch" in d for d in res["deviations"])
    assert any("no budget lock" in d for d in res["deviations"])


def test_drift_makes_p1prime_fail(tmp_path):
    cfgp, ledp, data, locks, events = _synthetic_study(tmp_path, drift=1.6)
    out = tmp_path / "o.json"
    assert _main(cfgp, ledp, data, locks, out).returncode == 0
    dec = json.loads(out.read_text())["decisions"]
    assert dec["P1prime_supported"] is False


def test_environment_exclusion_rule(tmp_path):
    cfgp, ledp, data, locks, events = _synthetic_study(tmp_path, n_pairs=9, broken_files=1)   # 1 of 9 files: 11%
    out = tmp_path / "o.json"
    r = _main(cfgp, ledp, data, locks, out)
    assert r.returncode != 0 and "no analysable pair" in r.stderr
    prun = {"files": {f"f{i}": {} for i in range(10)}, "tests": {f"f{i}::T::t": {} for i in range(9)}}
    bcol = {"collected": [f"f{i}::T::t" for i in range(10)], "meta": {"files": [f"f{i}" for i in range(10)]}}
    assert not E.environment_check(prun, bcol, CFG)["excluded"]                               # exactly 10%: kept
    prun["tests"].pop("f8::T::t")
    assert E.environment_check(prun, bcol, CFG)["excluded"]
