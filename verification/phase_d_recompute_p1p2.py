"""Independent recomputation of Phase D P1 and P2 (verification only; does NOT import phase_d_analysis.py).
Reads phase_d/data/assembled/*.json, phase_d/data/budget_lock/*.json, phase_d/events, phase_d/config.
Usage: python verification/phase_d_recompute_p1p2.py  -> prints JSON with P1/P2 and lock-budget comparison."""
import json, statistics, sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
A = R / "phase_d/data/assembled"
cfg = json.loads((R / "phase_d/config/phase_d_config.json").read_text())
evs = json.loads((R / "phase_d/events/phase_d_events.json").read_text())["events"]
BP = cfg["slice"]["backport_dir"] + "/"
T = cfg["runner"]["per_test_timeout_s"]
FR = (0.05, 0.25)

def ld(p): return json.loads(Path(p).read_text())
def fil(t): return t.split("::")[0]

def suite_of(ev, collected):
    own = BP + Path(ev["backport_file"]).name
    pre, bp = [], []
    for i, t in enumerate(collected):
        f = fil(t)
        if f.startswith(BP):
            if f == own:
                bp.append((ev["logical_file"] + "::" + t.split("::", 1)[1], i))
        else:
            pre.append((t, i))
    # CI order: sorted file path, then collection index; backport placed by method-name rule within its class
    keys = {t: (fil(t), i, 0, i) for t, i in pre}
    cls = {}
    for t, i in pre:
        cls.setdefault(t.rsplit("::", 1)[0], []).append((t.rsplit("::", 1)[1], i))
    for b, i in bp:
        if b in keys: continue
        mem = cls.get(b.rsplit("::", 1)[0], []); m = b.rsplit("::", 1)[1]
        lo = [j for n, j in mem if n < m]
        keys[b] = (fil(b), max(lo), 1, i) if lo else ((fil(b), min(j for _, j in mem), -1, i) if mem else (fil(b), float("inf"), 1, i))
    order = sorted(keys, key=keys.get)
    return order, {b for b, _ in bp}

def run(ev):
    P, B = ev["P"], ev["B"]
    order, bps = suite_of(ev, ld(A / f"collect_{B}.json")["collected"])
    prun = ld(A / f"run_w{P}_t{P}_pass1.json")["tests"]
    pd = {t: (T if r["outcome"] == "timeout" else r["duration"]) for t, r in prun.items() if not fil(t).startswith(BP)}
    byf = {}
    for t, d in pd.items(): byf.setdefault(fil(t), []).append(d)
    g = statistics.median(pd.values())
    est = {t: pd[t] if t in pd else (statistics.median(byf[fil(t)]) if len(byf.get(fil(t), [])) >= 3 else g) for t in order}
    own = BP + Path(ev["backport_file"]).name
    passes = []
    for k in (1, 2):
        p = A / f"run_w{B}_t{B}_pass{k}.json"
        if not p.exists(): continue
        m = {}
        for t, r in ld(p)["tests"].items():
            f = fil(t)
            if f.startswith(BP):
                if f != own: continue
                t = ev["logical_file"] + "::" + t.split("::", 1)[1]
            m[t] = T if r["outcome"] == "timeout" else r["duration"]
        passes.append(m)
    real = {t: (sum(m[t] for m in passes if t in m) / max(1, sum(1 for m in passes if t in m))) if any(t in m for m in passes) else est[t] for t in order}
    tot = sum(est.values())
    pos = {t: i for i, t in enumerate(order)}
    srt = sorted(order, key=lambda t: (est[t], pos[t]))
    out = {"total_est": tot, "pre_est": sum(est[t] for t in order if t not in bps),
           "pre_real": sum(real[t] for t in order if t not in bps)}
    out["P2_rel_err"] = out["pre_est"] / out["pre_real"] - 1
    for f in FR:
        b = f * tot
        cf, s = [], 0.0
        for t in srt:
            if s + est[t] <= b: cf.append(t); s += est[t]
        cov, cd, s, rest = set(), [], 0.0, []
        for t in srt:
            if fil(t) in cov: rest.append(t)
            elif s + est[t] <= b: cd.append(t); s += est[t]; cov.add(fil(t))
        for t in rest:
            if s + est[t] <= b: cd.append(t); s += est[t]
        out[str(f)] = {"budget": b,
                       "cheapest_first": sum(real[t] for t in cf if t not in bps) / b,
                       "coast_d": sum(real[t] for t in cd if t not in bps) / b}
    lk = ld(R / f"phase_d/data/budget_lock/{ev['event_id']}.json")
    out["lock_budget_match"] = all(abs(lk["budgets_s"][str(f)] - out[str(f)]["budget"]) < 1e-5 for f in FR)
    return out

res = {ev["event_id"]: run(ev) for ev in evs}
P1 = {}
for pol in ("cheapest_first", "coast_d"):
    for f in FR:
        xs = [res[e][str(f)][pol] for e in res]
        P1[f"{pol}@{f}"] = {"mean": sum(xs) / len(xs), "max": max(xs), "holds": sum(xs) / len(xs) <= 1.25 and max(xs) <= 2.0}
print(json.dumps({"per_event": res, "P1": P1, "P1_supported": all(v["holds"] for v in P1.values()),
                  "P2": {e: res[e]["P2_rel_err"] for e in res},
                  "P2_supported": all(abs(res[e]["P2_rel_err"]) <= 0.25 for e in res)}, indent=1))
