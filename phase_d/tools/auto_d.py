# Step driver used in the Phase D collection sandbox: it calls the runner once per plan step and keeps
# its position in a state file. R and ST below are sandbox-absolute paths (the original collection
# environment); adjust them to your own checkout before reuse.
"""Executes the next step of a plan (one runner invocation per call). State in auto_d_state.json."""
import json, subprocess, sys, time
from pathlib import Path
R = "/sessions/admiring-eager-pasteur/mnt/Paper 2 - Selection/phase_d/runner/run_phase_d.py"
ST = Path("/sessions/admiring-eager-pasteur/mnt/outputs/phasec/auto_d_state.json")
plan = json.loads(Path(sys.argv[1]).read_text())
st = json.loads(ST.read_text()) if ST.exists() else {}
idx = st.get(sys.argv[1], 0)
t0 = time.time()
while idx < len(plan) and time.time() - t0 < 25:
    step = plan[idx]
    out = subprocess.run(["python", R] + step, capture_output=True, text=True, timeout=165)
    last = (out.stdout.strip().splitlines() or [""])[-1]
    print(" ".join(step), "->", last[-220:], ("ERR:" + out.stderr[-400:]) if out.returncode else "")
    if out.returncode != 0:
        break
    if step[0] in ("run", "fcheck") and '"incomplete"' in last:
        break
    idx += 1
    st[sys.argv[1]] = idx; ST.write_text(json.dumps(st))
print("plan step", idx, "/", len(plan))
