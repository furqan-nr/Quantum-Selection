"""Phase E pre-registration check of the candidate releases (PREREGISTRATION_PHASE_E.md, Section 10, item 2).

For every version given: PyPI metadata (upload time, yanked flag, requires_python, the manylinux x86_64 wheel and the
sdist with their SHA-256), the sdist downloaded and its SHA-256 verified against PyPI, the NAMES of its members listed
(no file is executed or imported): whether test/python/transpiler and test/python/compiler exist, the number of slice
files (Phase E slice globs) and whether the excluded file exists; and a pip dependency resolution on Python 3.10 with
the Phase E constraints (`pip install --dry-run --report`: metadata only, nothing installed, no test executed, no timing).

    python3 phase_e/tools/check_releases.py --out phase_e/tools/release_checks.json 1.0.0 1.0.1 ...

Standard library + pip. Scratch: $PHASEE_ROOT/cache (default /tmp/phase_e/cache).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("PHASEE_ROOT", "/tmp/phase_e")) / "cache"
CONSTRAINTS = REPO / "phase_e/config/constraints.txt"
SLICE_GLOBS = ["test/python/transpiler/**/test_*.py", "test/python/compiler/test_*.py"]
EXCLUDE = "test/python/transpiler/test_unitary_synthesis_plugin.py"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def in_slice(rel: str) -> bool:
    if rel.startswith("test/python/compiler/"):
        return "/" not in rel[len("test/python/compiler/"):] and fnmatch.fnmatch(Path(rel).name, "test_*.py")
    if rel.startswith("test/python/transpiler/"):
        return fnmatch.fnmatch(Path(rel).name, "test_*.py")
    return False


def check(v: str, pypi: dict) -> dict:
    files = pypi["releases"][v]
    up = min(f["upload_time"] for f in files)
    whl = [f for f in files if f["packagetype"] == "bdist_wheel" and "x86_64" in f["filename"]
           and "manylinux" in f["filename"] and "abi3" in f["filename"]]
    sd = [f for f in files if f["packagetype"] == "sdist"]
    rec = {"version": v, "upload_time_utc": up, "yanked": any(f.get("yanked") for f in files),
           "requires_python": files[0].get("requires_python"),
           "wheel": {"filename": whl[0]["filename"], "sha256": whl[0]["digests"]["sha256"]} if whl else None,
           "sdist": {"filename": sd[0]["filename"], "sha256": sd[0]["digests"]["sha256"], "url": sd[0]["url"]} if sd else None}
    if sd:
        CACHE.mkdir(parents=True, exist_ok=True)
        p = CACHE / sd[0]["filename"]
        if not p.exists():
            with urllib.request.urlopen(sd[0]["url"], timeout=120) as r, open(p, "wb") as fh:
                fh.write(r.read())
        rec["sdist_sha256_ok"] = sha256(p) == sd[0]["digests"]["sha256"]
        with tarfile.open(p) as tf:
            names = [m.name.split("/", 1)[1] for m in tf.getmembers() if m.isfile() and "/" in m.name]
        sl = sorted(n for n in names if in_slice(n))
        rec["sdist_test_tree"] = {"has_transpiler_dir": any(n.startswith("test/python/transpiler/") for n in names),
                                  "has_compiler_dir": any(n.startswith("test/python/compiler/") for n in names),
                                  "n_slice_files_before_exclusion": len(sl),
                                  "excluded_file_present": EXCLUDE in names,
                                  "has_test_init": "test/__init__.py" in names}
    with tempfile.TemporaryDirectory() as td:
        rep = Path(td) / "r.json"
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
                            "--disable-pip-version-check", "--only-binary", ":all:", "--report", str(rep),
                            "-c", str(CONSTRAINTS), f"qiskit=={v}", "ddt", "hypothesis", "pytest"],
                           capture_output=True, text=True, timeout=160)
        rec["pip_resolution"] = {"rc": r.returncode, "stderr_tail": r.stderr[-600:]}
        if rep.exists():
            inst = json.loads(rep.read_text()).get("install", [])
            rec["pip_resolution"]["resolved"] = sorted(f"{i['metadata']['name']}=={i['metadata']['version']}" for i in inst)
            q = [i for i in inst if i["metadata"]["name"].lower() == "qiskit"]
            rec["pip_resolution"]["qiskit_artifact"] = q[0]["download_info"]["url"].rsplit("/", 1)[-1] if q else None
    rec["python"] = sys.version.split()[0]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("versions", nargs="+")
    a = ap.parse_args()
    out = Path(a.out)
    prev = json.loads(out.read_text()) if out.exists() else {"checks": {}}
    with urllib.request.urlopen("https://pypi.org/pypi/qiskit/json", timeout=60) as r:
        pypi = json.loads(r.read())
    for v in a.versions:
        prev["checks"][v] = check(v, pypi)
        c = prev["checks"][v]
        print(v, c["yanked"], c.get("sdist_sha256_ok"), c.get("sdist_test_tree", {}).get("n_slice_files_before_exclusion"),
              c["pip_resolution"]["rc"], c["pip_resolution"].get("qiskit_artifact"), flush=True)
    prev["checked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prev["constraints_sha256"] = sha256(CONSTRAINTS)
    out.write_text(json.dumps(prev, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
