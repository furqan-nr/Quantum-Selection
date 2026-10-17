"""Time-boxed wrapper around the frozen driver's chunk(): labels (event, unit) pairs in manifest order.
light mode: skips the four 12-qubit qft/random_clifford line units, stops starting new pairs after BOX seconds
            and never starts a pair whose predicted time (0.6 x session-B median) exceeds the time left.
heavy mode: labels the next missing pair of one heavy unit only."""
import os, sys, time, json, runpy, statistics
from pathlib import Path
cohort, out_root, mode, box = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
HEAVY = {"qft-n12-line-opt1", "qft-n12-line-opt3", "random_clifford-n12-line-opt1", "random_clifford-n12-line-opt3"}
ROOT = Path("/sessions/admiring-eager-pasteur/mnt/Paper 2 - Selection")
os.chdir(ROOT)
sys.argv = ["run_phase_c_ground_truth.py"]
drv = runpy.run_path(str(ROOT / "scripts/run_phase_c_ground_truth.py"), run_name="drv")
pred = json.load(open("/sessions/admiring-eager-pasteur/mnt/outputs/phasec/unit_cost_B.json"))
out = ROOT / out_root
ev_path = out / "events" / "events.json"
drv["_guard"](ev_path)
events = drv["load_events"](ev_path)
units = drv["units_for"](out)[:116]
t0 = time.time(); done = 0; left = {"light": 0, "heavy": 0}
for u in units:
    heavy = u.test_id in HEAVY
    for ev in events:
        if (out / "raw" / ev.event_id / u.test_id / "result.json").exists():
            continue
        left["heavy" if heavy else "light"] += 1
        if (mode == "light") == heavy:
            continue
        el = time.time() - t0
        need = 0.6 * pred.get(u.test_id, 1.0) + 2
        if (mode == "heavy" and done >= 1) or el > box or need > box - el + 15:
            continue
        drv["chunk"]([ev], [u], out, out_root, 5)
        done += 1; left["heavy" if heavy else "light"] -= 1
print(json.dumps({"cohort": cohort, "mode": mode, "done": done, "left": left, "elapsed_s": round(time.time() - t0, 1)}))
