#!/usr/bin/env python3
"""forward_probe_units.py - run the 116 corpus units on a forward-event revision pair and record raw observables.

Step 1 of "selectors on the forward events". It does NOT decide detection. For every unit and for BOTH builds
(baseline = last good, candidate = introducing commit) it records:
  * the transpile CPU times (``--repeats`` runs),
  * ``tqc.layout.initial_layout.get_registers()`` (the #14904/#15024 contract observable),
  * two-qubit count and depth of the output.
Detection rules are applied afterwards by scripts/forward_selector_eval.py, so they can be declared before the
numbers are looked at. Output is written incrementally and the run can be resumed.

Run from the repo root (the Paper 2 folder) in PowerShell, anchor venv active, PYTHONPATH=src:
  python scripts\\forward_probe_units.py --event fwd-applylayout-registers-14904
  python scripts\\forward_probe_units.py --event hist-vf2postlayout-noop
Optional: --limit 3 (smoke test), --repeats 5, --baseline-python / --candidate-python to override venvs.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROBE = r'''
import argparse, json, time, traceback
from pathlib import Path

def sig(tqc):
    layout = getattr(tqc, "layout", None)
    il = getattr(layout, "initial_layout", None) if layout is not None else None
    if il is None or not hasattr(il, "get_registers"):
        return None
    try:
        return sorted([[getattr(r, "name", "?"), int(len(r)), type(r).__name__] for r in il.get_registers()])
    except Exception as exc:
        return "__error__:" + type(exc).__name__

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family"); ap.add_argument("--n", type=int); ap.add_argument("--backend")
    ap.add_argument("--opt", type=int); ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1234); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"status": "ok"}
    try:
        import qiskit
        from qiskit.transpiler import generate_preset_pass_manager
        from cart.manifest.circuits import build
        from cart.manifest.backends import coupling_map_for
        out["qiskit_version"] = qiskit.__version__
        circ = build(a.family, a.n, seed=a.seed, measured=False)
        cmap = coupling_map_for(a.backend, circ.num_qubits)
        times, walls, tqc = [], [], None
        for _ in range(max(1, a.repeats)):
            pm = generate_preset_pass_manager(optimization_level=a.opt, coupling_map=cmap,
                                              basis_gates=["cx", "rz", "sx", "x"], seed_transpiler=a.seed)
            c0 = time.process_time(); w0 = time.perf_counter(); tqc = pm.run(circ)
            times.append(time.process_time() - c0); walls.append(time.perf_counter() - w0)
        ops = tqc.count_ops()
        out.update(cpu_times_s=times, wall_times_s=walls, registers=sig(tqc), depth=int(tqc.depth()),
                   n2q=int(sum(v for k, v in ops.items() if k in ("cx", "cz", "ecr", "swap"))))
    except Exception as exc:
        out.update(status="error", error_type=type(exc).__name__, error=str(exc)[:300],
                   traceback=traceback.format_exc()[-800:])
    Path(a.out).write_text(json.dumps(out))

main()
'''


def run_probe(py: str, unit, repeats: int, work: Path) -> dict:
    res = work / "r.json"
    if res.exists():
        res.unlink()
    opt = int(unit.transpiler_config_id.split("+")[0].removeprefix("opt"))
    cmd = [str(py), str(work / "probe.py"), "--family", unit.circuit_family, "--n", str(unit.n_qubits),
           "--backend", unit.backend_id, "--opt", str(opt), "--repeats", str(repeats), "--out", str(res)]
    env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
    try:
        subprocess.run(cmd, cwd=str(ROOT), env=env, check=True, capture_output=True, timeout=1800)
        return json.loads(res.read_text())
    except Exception as exc:   # subprocess crash / timeout
        return {"status": "error", "error_type": type(exc).__name__, "error": str(exc)[:300]}


def main(argv=None) -> int:
    from cart.events.table import load_events
    from cart.manifest.static_manifest import enumerate_costhet_units
    from cart.labels.historical_runner import _venv_python
    p = argparse.ArgumentParser()
    p.add_argument("--event", required=True)
    p.add_argument("--baseline-python"); p.add_argument("--candidate-python")
    p.add_argument("--repeats", type=int, default=None, help="default 5 for performance events, 2 otherwise")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    ev = {e.event_id: e for e in load_events()}[args.event]
    bpy = args.baseline_python or _venv_python(f"{ev.event_environment_id}-base")
    cpy = args.candidate_python or _venv_python(f"{ev.event_environment_id}-cand")
    if not bpy or not cpy:
        raise SystemExit(f"per-event venvs for {args.event} not found under environment\\_builds "
                         f"({ev.event_environment_id}-base / -cand). Pass --baseline-python / --candidate-python.")
    repeats = args.repeats or (5 if ev.fault_type.value == "performance" else 2)
    units = enumerate_costhet_units()
    if args.limit:
        units = units[:args.limit]
    out_path = Path(args.out) if args.out else ROOT / "results" / "forward_units" / f"{args.event}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(out_path.read_text()) if out_path.exists() else {}
    rec = data.get("records", {})
    work = Path(tempfile.mkdtemp(prefix="fwdprobe_"))
    (work / "probe.py").write_text(PROBE)
    t0 = time.time()
    for i, u in enumerate(units, 1):
        if u.test_id in rec and rec[u.test_id].get("baseline", {}).get("status") == "ok" \
                and rec[u.test_id].get("candidate", {}).get("status") == "ok":
            continue
        rec[u.test_id] = {"baseline": run_probe(bpy, u, repeats, work), "candidate": run_probe(cpy, u, repeats, work)}
        data = {"schema": "forward_units/v1", "event_id": args.event, "baseline_python": str(bpy),
                "candidate_python": str(cpy), "repeats": repeats, "records": rec}
        out_path.write_text(json.dumps(data, indent=1))
        b, c = rec[u.test_id]["baseline"], rec[u.test_id]["candidate"]
        print(f"[{i}/{len(units)}] {u.test_id}: base={b.get('status')} cand={c.get('status')} "
              f"regs_equal={b.get('registers') == c.get('registers')} elapsed={time.time()-t0:.0f}s", flush=True)
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
