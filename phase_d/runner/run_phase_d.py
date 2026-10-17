"""Phase D runner: resumable, chunked per-test timing of Qiskit's transpiler+compiler unit tests on release wheels
(PREREGISTRATION_PHASE_D.md, Section 6). Standard library only; the tests run in one venv per Qiskit version.

Commands (run from anywhere; paths are resolved from this file):
  prepare  --version V            download + verify wheel and sdist (SHA-256 frozen in the config), create the venv
                                  (identical pins), extract the sdist's test/ tree, add the backported tests of every
                                  event whose B == V
  collect  --version V            collect-only of the slice + backports (one process); used for the budget lock
  run      --version V --pass K [--wheel W]
                                  timing pass (refused for a B release whose events' budget locks are missing):
                                  every slice file in sorted order, one pytest process per file (a
                                  backported test file runs in the same process right after its logical file),
                                  per-test JSON lines; stops launching files after
                                  chunk_launch_limit_s and kills at chunk_hard_limit_s; re-invoke to resume
  fcheck   --event E              F-run: the event's backported tests + every pre-existing test that did not pass on B
                                  in some timing pass, executed from B's test tree against the F wheel
  assemble --version V --pass K [--wheel W] | --fcheck E | --collect V
                                  consolidate the JSON lines into one JSON per run (input of the analysis)
  status                          progress of every run directory
  cleanup  --version V            delete the venv and test tree of V under the scratch root

Per-test timeout: a test whose 'start' line is older than per_test_timeout_s is killed (process group), recorded as
outcome 'timeout' with duration = per_test_timeout_s, and the file is relaunched with completed and timed-out tests
deselected. A process that dies inside a test (e.g. Rust panic abort) records that test as 'crash'. A chunk kill
(hard limit) records nothing for the running test; the next call resumes the file, deselecting completed tests.

Scratch root (venvs, sdists, test trees): $PHASED_ROOT or /tmp/phase_d. Data: phase_d/data/ in the repository
(override with --data for the dry run). Linux is the registered platform; Windows paths are handled but untested.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CFG = json.loads((REPO / "phase_d/config/phase_d_config.json").read_text())
LEDGER = json.loads((REPO / "phase_d/events/phase_d_events.json").read_text())
ROOT = Path(os.environ.get("PHASED_ROOT", "/tmp/phase_d"))
IS_WIN = os.name == "nt"


# ----------------------------------------------------------------------------------------------- helpers
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def vinfo(v: str) -> dict:
    return CFG["versions"].get(v) or CFG["dryrun_versions_outside_study"][v]


def venv_python(v: str) -> Path:
    d = ROOT / "venvs" / v
    return d / ("Scripts/python.exe" if IS_WIN else "bin/python")


def tests_dir(v: str) -> Path:
    return ROOT / "tests" / v


def pinned_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update(CFG["environment"]["pinned_env"])
    env["PYTHONPATH"] = str(HERE)            # only phased_plugin.py / calibrate.py live here
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    if extra:
        env.update(extra)
    return env


def slice_files(v: str) -> list[str]:
    base = tests_dir(v)
    out = set()
    for g in CFG["slice"]["include_globs"]:
        for p in glob.glob(str(base / g), recursive=True):
            out.add(Path(p).relative_to(base).as_posix())
    return sorted(out - set(CFG["slice"]["exclude_files"]))


def events_with_B(v: str) -> list[dict]:
    return [e for e in LEDGER["events"] if e["B"] == v]


def backport_files(v: str) -> list[str]:
    d = CFG["slice"]["backport_dir"]
    return sorted(f"{d}/{Path(e['backport_file']).name}" for e in events_with_B(v))


def run_units(v: str) -> list[list[str]]:
    """Execution units of a timing pass: each slice file in sorted order; a backported test file of an event with
    B == v runs in the same process right after its logical file (as if appended to it, warm process)."""
    units = {f: [f] for f in slice_files(v)}
    tail = []
    for e in sorted(events_with_B(v), key=lambda e: e["event_id"]):
        bp = f"{CFG['slice']['backport_dir']}/{Path(e['backport_file']).name}"
        (units[e["logical_file"]] if e["logical_file"] in units else tail).append(bp)
    return [units[f] for f in sorted(units)] + [[b] for b in tail]


def runner_hashes() -> dict:
    return {p.name: sha256(p) for p in (HERE / "run_phase_d.py", HERE / "phased_plugin.py", HERE / "calibrate.py")}


def env_record(py: Path, extra: dict) -> dict:
    cpu = ""
    try:
        cpu = next(ln.split(":", 1)[1].strip() for ln in open("/proc/cpuinfo") if ln.startswith("model name"))
    except Exception:
        cpu = platform.processor()
    cal = {}
    try:
        r = subprocess.run([str(py), str(HERE / "calibrate.py")], capture_output=True, text=True, timeout=60,
                           env=pinned_env())
        cal = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as exc:                                   # recorded, never fatal
        cal = {"error": repr(exc)}
    rec = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": platform.node(),
           "platform": platform.platform(), "runner_python": sys.version.split()[0], "cpu_model": cpu,
           "nproc": os.cpu_count(), "loadavg": (os.getloadavg() if hasattr(os, "getloadavg") else None),
           "pinned_env": CFG["environment"]["pinned_env"], "runner_sha256": runner_hashes(), **cal, **extra}
    fz = py.parent.parent / "freeze.txt"
    if fz.exists():
        rec["venv_freeze_sha256"] = sha256(fz)
    return rec


# ----------------------------------------------------------------------------------------------- prepare
def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)


def cmd_prepare(a) -> None:
    v = a.version
    info = vinfo(v)
    cache = ROOT / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    whl = cache / info["wheel"]["filename"]
    if not whl.exists():
        subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary", ":all:",
                        f"qiskit=={v}", "-d", str(cache)], check=True)
    if sha256(whl) != info["wheel"]["sha256"]:
        raise SystemExit(f"wheel sha256 mismatch for {v}")
    sd = cache / info["sdist"]["filename"]
    if not sd.exists():
        download(info["sdist"]["url"], sd)
    if sha256(sd) != info["sdist"]["sha256"]:
        raise SystemExit(f"sdist sha256 mismatch for {v}")
    py = venv_python(v)
    if not py.exists():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / "venvs" / v)], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-c", str(REPO / CFG["environment"]["constraints_file"]), str(whl),
                        *CFG["environment"]["pip_extra"]], check=True)
        fz = subprocess.run([str(py), "-m", "pip", "freeze"], capture_output=True, text=True, check=True).stdout
        (ROOT / "venvs" / v / "freeze.txt").write_text(fz)
    td = tests_dir(v)
    if not (td / "test").exists():
        td.mkdir(parents=True, exist_ok=True)
        prefix = f"qiskit-{v}/test/"
        with tarfile.open(sd) as tf:
            members = [m for m in tf.getmembers() if m.name.startswith(prefix) and m.isfile()]
            for m in members:
                rel = m.name[len(f"qiskit-{v}/"):]
                out = td / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, open(out, "wb") as fh:
                    shutil.copyfileobj(src, fh)
    bdir = td / CFG["slice"]["backport_dir"]
    evs = events_with_B(v)
    if evs:
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "__init__.py").write_text("")
        for e in evs:
            shutil.copyfile(REPO / e["backport_file"], bdir / Path(e["backport_file"]).name)
    print(json.dumps({"prepared": v, "python": str(py), "tests": str(td), "slice_files": len(slice_files(v)),
                      "backports": backport_files(v)}))


# ----------------------------------------------------------------------------------------------- run one file
def _read_new(path: Path, offset: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], offset
    with open(path, encoding="utf-8") as fh:
        fh.seek(offset)
        data = fh.read()
    # keep an incomplete trailing line for the next read
    cut = data.rfind("\n") + 1
    recs = [json.loads(ln) for ln in data[:cut].splitlines() if ln.strip()]
    return recs, offset + len(data[:cut].encode("utf-8"))


def _file_state(jl: Path) -> tuple[set, dict | None]:
    """completed ids (done records, incl. synthetic) and the open start (if any)."""
    done, open_start = set(), None
    recs, _ = _read_new(jl, 0)
    for r in recs:
        if r["ev"] == "start":
            open_start = r
        elif r["ev"] == "done":
            done.add(r["id"])
            if open_start and open_start["id"] == r["id"]:
                open_start = None
        elif r["ev"] == "launch":
            open_start = None
    return done, open_start


def _kill(proc: subprocess.Popen) -> None:
    try:
        if IS_WIN:
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_file(py: Path, cwd: Path, paths: list[str], jl: Path, hard_deadline: float, only: set | None = None) -> str:
    """Run one unit (a slice file, followed in the SAME process by the backported test files whose logical file it
    is) until every collected test has a record; handles timeouts, crashes and the chunk hard limit."""
    T = float(CFG["runner"]["per_test_timeout_s"])
    poll = float(CFG["runner"]["poll_s"])
    marker = jl.with_suffix(".done.json")
    wall = 0.0
    launches = 0
    while True:
        done, _ = _file_state(jl)
        skipf = jl.with_suffix(".skip")
        skipf.write_text("".join(i + "\n" for i in sorted(done)))
        extra = {"PHASED_OUT": str(jl), "PHASED_SKIP": str(skipf)}
        if only is not None:
            onlyf = jl.with_suffix(".only")
            onlyf.write_text("".join(i + "\n" for i in sorted(only)))
            extra["PHASED_ONLY"] = str(onlyf)
        with open(jl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ev": "launch", "n": launches, "t": time.time(), "skip": len(done)}) + "\n")
        offset = jl.stat().st_size
        log = open(jl.with_suffix(".log"), "a", encoding="utf-8")
        t0 = time.time()
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {"start_new_session": True}
        proc = subprocess.Popen([str(py), "-m", "pytest", *CFG["environment"]["pytest_args"], *paths], cwd=str(cwd),
                                env=pinned_env(extra), stdout=log, stderr=subprocess.STDOUT, **kw)
        launches += 1
        current = None
        verdict = None
        while proc.poll() is None:
            time.sleep(poll)
            recs, offset = _read_new(jl, offset)
            for r in recs:
                if r["ev"] == "start":
                    current = r
                elif r["ev"] == "done" and current and r["id"] == current["id"]:
                    current = None
            now = time.time()
            if current and now - current["t"] > T:
                _kill(proc)
                with open(jl, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ev": "done", "id": current["id"], "outcome": "timeout", "setup": 0.0,
                                         "call": T, "teardown": 0.0, "duration": T, "synthetic": "timeout"},
                                        sort_keys=True) + "\n")
                verdict = "relaunch"
                break
            if now > hard_deadline:
                _kill(proc)
                verdict = "incomplete"
                break
        wall += time.time() - t0
        log.close()
        if verdict == "incomplete":
            return "incomplete"
        if verdict == "relaunch":
            continue
        recs, offset = _read_new(jl, offset)
        for r in recs:
            if r["ev"] == "start":
                current = r
            elif r["ev"] == "done" and current and r["id"] == current["id"]:
                current = None
        rc = proc.returncode
        if current is not None:                    # died inside a test: crash
            with open(jl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ev": "done", "id": current["id"], "outcome": "crash", "setup": 0.0,
                                     "call": time.time() - current["t"], "teardown": 0.0,
                                     "duration": time.time() - current["t"], "synthetic": "crash", "rc": rc},
                                    sort_keys=True) + "\n")
            continue
        marker.write_text(json.dumps({"unit": paths, "rc": rc, "wall_s_this_call": wall, "launches_this_call": launches}))
        return "done"


def slug(rel: str) -> str:
    return rel.replace("/", "__")


def run_files(py: Path, cwd: Path, units: list[list[str]], outdir: Path, env_extra: dict, only: set | None = None) -> None:
    t_call = time.time()
    lim = float(CFG["runner"]["chunk_launch_limit_s"])
    hard = t_call + float(CFG["runner"]["chunk_hard_limit_s"])
    (outdir / "files").mkdir(parents=True, exist_ok=True)
    (outdir / "env").mkdir(parents=True, exist_ok=True)
    rec = env_record(py, env_extra)
    (outdir / "env" / f"call_{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{os.getpid()}.json").write_text(
        json.dumps(rec, indent=1))
    n_done = n_run = 0
    status = "complete"
    for unit in units:
        jl = outdir / "files" / (slug(unit[0]) + ".jsonl")
        if jl.with_suffix(".done.json").exists():
            n_done += 1
            continue
        if time.time() - t_call > lim:
            status = "incomplete"
            break
        r = run_file(py, cwd, unit, jl, hard, only)
        n_run += 1
        if r == "done":
            n_done += 1
        else:
            status = "incomplete"
            break
    if n_done == len(units):
        (outdir / "COMPLETE.json").write_text(json.dumps({"units": len(units), "utc": rec["utc"]}))
    print(json.dumps({"outdir": str(outdir), "status": status, "files_done": n_done, "files_total": len(units),
                      "ran_this_call": n_run, "call_s": round(time.time() - t_call, 1)}))


def data_root(a) -> Path:
    return Path(a.data) if getattr(a, "data", None) else REPO / "phase_d/data"


def missing_locks(v: str, root: Path) -> list[str]:
    """Events with B == v whose budget lock (phase_d/data/budget_lock/<E>.json) does not exist yet."""
    return [e["event_id"] for e in events_with_B(v) if not (root / "budget_lock" / f"{e['event_id']}.json").exists()]


def cmd_run(a) -> None:
    v, w = a.version, (a.wheel or a.version)
    if w == v and not a.files and not getattr(a, "data", None):
        miss = missing_locks(v, data_root(a))
        if miss:                                   # Section 7: budgets are locked before any B timing pass
            raise SystemExit(f"{v} is B of {', '.join(miss)}: write their budget locks first "
                             f"(phase_d_analysis.py --lock {' '.join(miss)})")
    units = [[f] for f in a.files] if a.files else run_units(v)
    outdir = data_root(a) / "runs" / f"w{w}_t{v}" / f"pass{a.pass_}"
    run_files(venv_python(w), tests_dir(v), units, outdir, {"wheel": w, "tests": v, "pass": a.pass_, "mode": "run"})


def cmd_collect(a) -> None:
    v = a.version
    outdir = data_root(a) / "collect" / v
    outdir.mkdir(parents=True, exist_ok=True)
    jl = outdir / "collected.jsonl"
    if jl.exists():
        jl.unlink()
    files = list(a.files) if a.files else slice_files(v) + backport_files(v)
    py = venv_python(v)
    rec = env_record(py, {"wheel": v, "tests": v, "mode": "collect"})
    t0 = time.time()
    r = subprocess.run([str(py), "-m", "pytest", *CFG["environment"]["pytest_args"], "--collect-only",
                        "--continue-on-collection-errors", *files], cwd=str(tests_dir(v)),
                       env=pinned_env({"PHASED_OUT": str(jl)}), capture_output=True, text=True, timeout=600)
    (outdir / "collect.log").write_text(r.stdout[-20000:] + r.stderr[-5000:])
    rec.update({"rc": r.returncode, "collect_s": time.time() - t0, "files": files})
    (outdir / "COMPLETE.json").write_text(json.dumps(rec, indent=1))
    n = sum(1 for ln in open(jl) if '"collected"' in ln) if jl.exists() else 0
    print(json.dumps({"collected": n, "rc": r.returncode, "s": round(time.time() - t0, 1)}))


def _event(eid: str) -> dict:
    return next(e for e in LEDGER["events"] if e["event_id"] == eid)


def cmd_fcheck(a) -> None:
    e = _event(a.event)
    B, F = e["B"], e["F"]
    bad = set()
    runs = data_root(a) / "runs" / f"w{B}_t{B}"
    for k in range(1, CFG["runner"]["timing_passes_B"] + 1):
        for jl in sorted((runs / f"pass{k}" / "files").glob("*.jsonl")):
            for r in _read_new(jl, 0)[0]:
                if r["ev"] == "done" and r["outcome"] in ("failed", "error", "timeout", "crash"):
                    bad.add(r["id"])
    bp = f"{CFG['slice']['backport_dir']}/{Path(e['backport_file']).name}"
    files = sorted({i.split("::", 1)[0] for i in bad if not i.startswith(CFG["slice"]["backport_dir"])} | {bp})
    only = {i for i in bad if not i.startswith(CFG["slice"]["backport_dir"])}
    outdir = data_root(a) / "fcheck" / a.event
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "selection.json").write_text(json.dumps({"B": B, "F": F, "pre_existing_non_pass": sorted(only),
                                                       "files": files}, indent=1))
    pre = [f for f in files if f != bp]
    if pre:
        run_files(venv_python(F), tests_dir(B), [[f] for f in pre], outdir / "pre_existing", {"wheel": F, "tests": B, "mode": "fcheck"},
                  only)
    run_files(venv_python(F), tests_dir(B), [[bp]], outdir / "backport", {"wheel": F, "tests": B, "mode": "fcheck"})


# ----------------------------------------------------------------------------------------------- assemble
def assemble_dir(d: Path) -> dict:
    tests, files = {}, {}
    for jl in sorted((d / "files").glob("*.jsonl")):
        recs = _read_new(jl, 0)[0]
        rel = jl.name[:-len(".jsonl")].replace("__", "/")
        n_launch = 0
        coll = []
        for r in recs:
            if r["ev"] == "launch":
                n_launch += 1
            elif r["ev"] == "collected" and n_launch == 1:     # collection order of the first launch
                coll.append(r)
            elif r["ev"] == "done" and r["id"] not in tests:
                tests[r["id"]] = {"outcome": r["outcome"], "duration": r["duration"], "file": r["id"].split("::", 1)[0],
                                  "synthetic": r.get("synthetic")}
        m = jl.with_suffix(".done.json")
        files[rel] = {"complete": m.exists(), "marker": json.loads(m.read_text()) if m.exists() else None,
                      "collected": [c["id"] for c in sorted(coll, key=lambda c: c["idx"])],
                      "launches": sum(1 for r in recs if r["ev"] == "launch")}
    envs = [json.loads(p.read_text()) for p in sorted((d / "env").glob("*.json"))] if (d / "env").exists() else []
    return {"tests": tests, "files": files, "env": envs, "complete": (d / "COMPLETE.json").exists()}


def cmd_assemble(a) -> None:
    root = data_root(a)
    out = root / "assembled"
    out.mkdir(parents=True, exist_ok=True)
    if a.fcheck:
        d = root / "fcheck" / a.fcheck
        res = {"pre_existing": assemble_dir(d / "pre_existing") if (d / "pre_existing").exists() else None,
               "backport": assemble_dir(d / "backport")}
        name = f"fcheck_{a.fcheck}.json"
    elif a.collect:
        jl = root / "collect" / a.collect / "collected.jsonl"
        recs = _read_new(jl, 0)[0]
        res = {"collected": [r["id"] for r in sorted(recs, key=lambda r: r["idx"]) if r["ev"] == "collected"],
               "meta": json.loads((root / "collect" / a.collect / "COMPLETE.json").read_text())}
        name = f"collect_{a.collect}.json"
    else:
        w = a.wheel or a.version
        res = assemble_dir(root / "runs" / f"w{w}_t{a.version}" / f"pass{a.pass_}")
        name = f"run_w{w}_t{a.version}_pass{a.pass_}.json"
    (out / name).write_text(json.dumps(res, indent=0, sort_keys=True))
    print(json.dumps({"wrote": str(out / name)}))


def cmd_status(a) -> None:
    root = data_root(a)
    for d in sorted((root / "runs").glob("*/pass*")) + sorted((root / "fcheck").glob("*/*")):
        if not (d / "files").exists():
            continue
        n = len(list((d / "files").glob("*.done.json")))
        print(f"{d.relative_to(root)}: files done {n}, complete={(d / 'COMPLETE.json').exists()}")
    for d in sorted((root / "collect").glob("*")):
        print(f"{d.relative_to(root)}: complete={(d / 'COMPLETE.json').exists()}")


def cmd_cleanup(a) -> None:
    for p in (ROOT / "venvs" / a.version, ROOT / "tests" / a.version):
        shutil.rmtree(p, ignore_errors=True)
    print(json.dumps({"removed": a.version}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data root (default phase_d/data); the dry run uses a separate root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--version", required=True)
    p = sub.add_parser("collect"); p.add_argument("--version", required=True)
    p.add_argument("--files", nargs="*", help="dry run only: restrict to these files")
    p = sub.add_parser("run"); p.add_argument("--version", required=True); p.add_argument("--wheel")
    p.add_argument("--pass", dest="pass_", type=int, required=True)
    p.add_argument("--files", nargs="*", help="dry run only: restrict to these files")
    p = sub.add_parser("fcheck"); p.add_argument("--event", required=True)
    p = sub.add_parser("assemble"); p.add_argument("--version"); p.add_argument("--wheel")
    p.add_argument("--pass", dest="pass_", type=int); p.add_argument("--fcheck"); p.add_argument("--collect")
    sub.add_parser("status")
    p = sub.add_parser("cleanup"); p.add_argument("--version", required=True)
    a = ap.parse_args()
    {"prepare": cmd_prepare, "collect": cmd_collect, "run": cmd_run, "fcheck": cmd_fcheck, "assemble": cmd_assemble,
     "status": cmd_status, "cleanup": cmd_cleanup}[a.cmd](a)


if __name__ == "__main__":
    main()
