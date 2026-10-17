"""pytest plugin of the Phase D runner (PREREGISTRATION_PHASE_D.md, Section 6). Loaded with ``-p phased_plugin``.

Writes one JSON line per event to $PHASED_OUT, flushed immediately, so that a killed process loses nothing:
  {"ev": "collected", "id": <normalized id>, "raw": <nodeid>, "idx": <collection index>}
  {"ev": "start", "id": ..., "t": <unix time>}
  {"ev": "done", "id": ..., "outcome": passed|failed|error|skipped|xfailed|xpassed,
   "setup": s, "call": s, "teardown": s, "duration": setup+call+teardown}
Normalized id: every hex address (0x followed by >= 6 hex digits) replaced by '0x?' (ddt names embed object reprs,
e.g. '..._GenericBackendV2_object_at_0x772b46dca620_...'), and a '#k' suffix for
the k-th repeat of an otherwise identical id in collection order.
$PHASED_SKIP (optional): file with one normalized id per line to deselect (completed or timed-out tests on resume).
$PHASED_ONLY (optional): file with one normalized id per line; every other test is deselected (F-check runs).
Also imports unittest.mock (some Qiskit tests use it without importing it; harness shim).
"""
from __future__ import annotations

import json
import os
import re
import time
import unittest.mock  # noqa: F401  (harness shim)

_ADDR = re.compile(r"0x[0-9a-fA-F]{6,}")
_OUT = None
_IDS: dict[str, str] = {}
_ACC: dict[str, dict] = {}


def normalize(nodeid: str) -> str:
    return _ADDR.sub("0x?", nodeid)


def _emit(rec: dict) -> None:
    global _OUT
    if _OUT is None:
        path = os.environ.get("PHASED_OUT")
        if not path:
            return
        _OUT = open(path, "a", buffering=1, encoding="utf-8")
    _OUT.write(json.dumps(rec, sort_keys=True) + "\n")
    _OUT.flush()


def _read_ids(var: str):
    p = os.environ.get(var)
    if not p or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return {ln.rstrip("\n") for ln in fh if ln.strip()}


def pytest_collection_modifyitems(session, config, items):
    seen: dict[str, int] = {}
    skip = _read_ids("PHASED_SKIP") or set()
    only = _read_ids("PHASED_ONLY")
    keep, desel = [], []
    for idx, it in enumerate(items):
        n = normalize(it.nodeid)
        k = seen.get(n, 0)
        seen[n] = k + 1
        nid = n if k == 0 else f"{n}#{k}"
        _IDS[it.nodeid] = nid
        _emit({"ev": "collected", "id": nid, "raw": it.nodeid, "idx": idx})
        if nid in skip or (only is not None and nid not in only):
            desel.append(it)
        else:
            keep.append(it)
    if desel:
        config.hook.pytest_deselected(items=desel)
        items[:] = keep


def pytest_runtest_logstart(nodeid, location):
    nid = _IDS.get(nodeid, normalize(nodeid))
    _ACC[nodeid] = {"setup": 0.0, "call": 0.0, "teardown": 0.0, "outcome": None}
    _emit({"ev": "start", "id": nid, "t": time.time()})


def pytest_runtest_logreport(report):
    acc = _ACC.setdefault(report.nodeid, {"setup": 0.0, "call": 0.0, "teardown": 0.0, "outcome": None})
    acc[report.when] = float(getattr(report, "duration", 0.0) or 0.0)
    if hasattr(report, "wasxfail"):
        out = "xfailed" if report.skipped else "xpassed"
    elif report.failed:
        out = "failed" if report.when == "call" else "error"
    elif report.skipped:
        out = "skipped"
    else:
        out = "passed"
    prev = acc["outcome"]
    rank = {None: 0, "passed": 1, "skipped": 2, "xpassed": 2, "xfailed": 2, "failed": 3, "error": 4}
    if rank[out] >= rank[prev]:
        acc["outcome"] = out
    if report.when == "teardown":
        nid = _IDS.get(report.nodeid, normalize(report.nodeid))
        _emit({"ev": "done", "id": nid, "outcome": acc["outcome"], "setup": acc["setup"], "call": acc["call"],
               "teardown": acc["teardown"], "duration": acc["setup"] + acc["call"] + acc["teardown"]})
