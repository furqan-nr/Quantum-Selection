"""Phase E runner: resumable, chunked per-test timing of Qiskit's transpiler+compiler unit tests on release wheels
(PREREGISTRATION_PHASE_E.md, Section 5). Adapted from phase_d/runner/run_phase_d.py: same measurement code (process
per file, per-test JSON lines, 60-s per-test timeout, chunking and resumption, environment record with calibration);
differences: no backported tests and no F checks, events are release pairs (phase_e/events/phase_e_pairs.json),
data root phase_e/data/, scratch /tmp/phase_e, and a B timing pass additionally requires the public push of the
budget locks to be recorded (`confirm-lock-push`).

Commands (run from anywhere; paths are resolved from this file):
  prepare  --version V            download + verify wheel and sdist (SHA-256 frozen in the config), create the venv
                                  (identical pins), extract the sdist's test/ tree
  collect  --version V            collect-only of the slice (one process); input of the budget lock
  run      --version V --pass K   timing pass. For a B release it is refused unless the budget locks of every pair
                                  exist AND budget_lock/LOCK_PUSHED.json records the commit that published them (and
                                  the lock files still have the recorded SHA-256). Every slice file in sorted order,
                                  one pytest process per file, per-test JSON lines; stops launching files after
                                  chunk_launch_limit_s and kills at chunk_hard_limit_s; re-invoke to resume
  confirm-lock-push --commit SHA  record that the user pushed phase_e/data/budget_lock/ (commit SHA, UTC, lock hashes)
  assemble --version V --pass K | --collect V
                                  consolidate the JSON lines into one JSON per run (input of the analysis)
  status                          progress of every run directory
  cleanup  --version V [--keep-tests]
                                  delete the venv (and the test tree unless --keep-tests) of V under the scratch root

Scratch root (venvs, sdists, test trees): $PHASEE_ROOT or /tmp/phase_e. Data: phase_e/data/ in the repository
(override with --data for the dry run, which may only use releases listed in dryrun_versions_outside_study).
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
CFG = json.loads((REPO / "phase_e/config/phase_e_config.json").read_text())
LEDGER = json.loads((REPO / "phase_e/events/phase_e_pairs.json").read_text())
ROOT = Path(os.environ.get("PHASEE_ROOT", "/tmp/phase_e"))
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


def is_study(v: str) -> bool:
    return v in CFG["versions"]


def venv_python(v: str) -> Path:
    d = ROOT / "venvs" / v
    return d / ("Scripts/python.exe" if IS_WIN else "bin/python")


def tests_dir(v: str) -> Path:
    return ROOT / "tests" / v


def pinned_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update(CFG["environment"]["pinned_env"])
    env["PYTHONPATH"] = str(HERE)            # only phasee_plugin.py / calibrate.py live here
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


def pairs_with_B(v: str) -> list[dict]:
    return [e for e in LEDGER["events"] if e["B"] == v]


def runner_hashes() -> dict:
    return {p.name: sha256(p) for p in (HERE / "run_phase_e.py", HERE / "phasee_plugin.py", HERE / "calibrate.py")}


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
    print(json.dumps({"prepared": v, "python": str(py), "tests": str(td), "slice_files": len(slice_files(v))}))


# ----------------------------------------------------------------------------------------------- run one file
def _read_new(path: Path, offset: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], offset
    with open(path, encoding="utf-8") as fh:
        fh.seek(offset)
        data = fh.read()
    cut = data.rfind("\n") + 1                     # keep an incomplete trailing line for the next read
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


def run_file(py: Path, cwd: Path, paths: list[str], jl: Path, hard_deadline: float) -> str:
    """Run one slice file until every collected test has a record; handles timeouts, crashes and the chunk hard limit."""
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


def run_files(py: Path, cwd: Path, units: list[list[str]], outdir: Path, env_extra: dict) -> None:
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
        r = run_file(py, cwd, unit, jl, hard)
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
    return Path(a.data).resolve() if getattr(a, "data", None) else REPO / "phase_e/data"


def lock_gate(v: str, root: Path) -> list[str]:
    """Reasons a B timing pass of v must be refused (empty list = allowed)."""
    lockdir = root / "budget_lock"
    why = [f"missing lock {e['event_id']}" for e in LEDGER["events"] if not (lockdir / f"{e['event_id']}.json").exists()]
    pushed = lockdir / "LOCK_PUSHED.json"
    if not pushed.exists():
        why.append("budget_lock/LOCK_PUSHED.json missing (run confirm-lock-push after the user has pushed the locks)")
    else:
        rec = json.loads(pushed.read_text())
        for name, h in rec.get("lock_sha256", {}).items():
            p = lockdir / name
            if not p.exists() or sha256(p) != h:
                why.append(f"{name} changed after the recorded push")
        if set(rec.get("lock_sha256", {})) != {f"{e['event_id']}.json" for e in LEDGER["events"]}:
            why.append("LOCK_PUSHED.json does not cover every pair's lock")
    return why


def cmd_run(a) -> None:
    v = a.version
    if getattr(a, "data", None):
        if is_study(v):
            raise SystemExit(f"{v} is a Phase E study release: --data (dry-run root) is not allowed for it")
    elif not is_study(v):
        raise SystemExit(f"{v} is not a Phase E study release (use --data for a dry run)")
    if is_study(v) and pairs_with_B(v):
        why = lock_gate(v, data_root(a))
        if why:
            raise SystemExit(f"{v} is B of {', '.join(e['event_id'] for e in pairs_with_B(v))}; refused: " + "; ".join(why))
    units = [[f] for f in a.files] if a.files else [[f] for f in slice_files(v)]
    if a.files and is_study(v):
        raise SystemExit("--files is a dry-run option")
    outdir = data_root(a) / "runs" / f"w{v}_t{v}" / f"pass{a.pass_}"
    run_files(venv_python(v), tests_dir(v), units, outdir, {"wheel": v, "tests": v, "pass": a.pass_, "mode": "run"})


def cmd_collect(a) -> None:
    v = a.version
    if getattr(a, "data", None) and is_study(v):
        raise SystemExit(f"{v} is a Phase E study release: --data is not allowed for it")
    outdir = data_root(a) / "collect" / v
    outdir.mkdir(parents=True, exist_ok=True)
    jl = outdir / "collected.jsonl"
    if jl.exists():
        jl.unlink()
    files = list(a.files) if a.files else slice_files(v)
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


def cmd_confirm_lock_push(a) -> None:
    lockdir = data_root(a) / "budget_lock"
    locks = {p.name: sha256(p) for p in sorted(lockdir.glob("E*.json"))}
    if set(locks) != {f"{e['event_id']}.json" for e in LEDGER["events"]}:
        raise SystemExit(f"locks present {sorted(locks)} do not cover every pair")
    out = lockdir / "LOCK_PUSHED.json"
    if out.exists():
        raise SystemExit("LOCK_PUSHED.json already exists; it is never rewritten")
    if not a.commit or len(a.commit) < 7:
        raise SystemExit("give the commit SHA that published phase_e/data/budget_lock/")
    out.write_text(json.dumps({"commit": a.commit, "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "lock_sha256": locks}, indent=1, sort_keys=True))
    print(json.dumps({"wrote": str(out)}))


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
    if a.collect:
        jl = root / "collect" / a.collect / "collected.jsonl"
        recs = _read_new(jl, 0)[0]
        res = {"collected": [r["id"] for r in sorted(recs, key=lambda r: r["idx"]) if r["ev"] == "collected"],
               "meta": json.loads((root / "collect" / a.collect / "COMPLETE.json").read_text())}
        name = f"collect_{a.collect}.json"
    else:
        res = assemble_dir(root / "runs" / f"w{a.version}_t{a.version}" / f"pass{a.pass_}")
        name = f"run_w{a.version}_t{a.version}_pass{a.pass_}.json"
    (out / name).write_text(json.dumps(res, indent=0, sort_keys=True))
    print(json.dumps({"wrote": str(out / name)}))


def cmd_status(a) -> None:
    root = data_root(a)
    for d in sorted((root / "runs").glob("*/pass*")):
        if not (d / "files").exists():
            continue
        n = len(list((d / "files").glob("*.done.json")))
        print(f"{d.relative_to(root)}: files done {n}, complete={(d / 'COMPLETE.json').exists()}")
    for d in sorted((root / "collect").glob("*")):
        print(f"{d.relative_to(root)}: complete={(d / 'COMPLETE.json').exists()}")


def cmd_cleanup(a) -> None:
    paths = [ROOT / "venvs" / a.version] + ([] if a.keep_tests else [ROOT / "tests" / a.version])
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)
    print(json.dumps({"removed": [str(p) for p in paths]}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data root (default phase_e/data); the dry run uses a separate root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--version", required=True)
    p = sub.add_parser("collect"); p.add_argument("--version", required=True)
    p.add_argument("--files", nargs="*", help="dry run only: restrict to these files")
    p = sub.add_parser("run"); p.add_argument("--version", required=True)
    p.add_argument("--pass", dest="pass_", type=int, required=True)
    p.add_argument("--files", nargs="*", help="dry run only: restrict to these files")
    p = sub.add_parser("confirm-lock-push"); p.add_argument("--commit", required=True)
    p = sub.add_parser("assemble"); p.add_argument("--version"); p.add_argument("--pass", dest="pass_", type=int)
    p.add_argument("--collect")
    sub.add_parser("status")
    p = sub.add_parser("cleanup"); p.add_argument("--version", required=True); p.add_argument("--keep-tests", action="store_true")
    a = ap.parse_args()
    {"prepare": cmd_prepare, "collect": cmd_collect, "run": cmd_run, "confirm-lock-push": cmd_confirm_lock_push,
     "assemble": cmd_assemble, "status": cmd_status, "cleanup": cmd_cleanup}[a.cmd](a)


if __name__ == "__main__":
    main()
