import json, math, statistics, sys
from pathlib import Path
A=Path("/sessions/admiring-eager-pasteur/mnt/Paper 2 - Selection/phase_d/data/assembled")
PAIRS=[("2.0.1","2.0.2"),("2.0.3","2.1.0"),("2.1.2","2.2.0rc1"),("2.2.1","2.2.2"),("2.4.2","2.5.0"),("2.5.0","2.5.1")]
BP="test/python/phase_d_backport/"
T=60.0
def ld(p): return json.loads(p.read_text())
def fil(t): return t.split("::",1)[0]
def dur(r): return T if r["outcome"]=="timeout" else float(r["duration"])
def q(xs,p):
    xs=sorted(xs); 
    if not xs: return 0
    k=(len(xs)-1)*p; f=math.floor(k); c=min(f+1,len(xs)-1); return xs[f]+(xs[c]-xs[f])*(k-f)
data={}
for P,B in PAIRS:
    pr=ld(A/f"run_w{P}_t{P}_pass1.json")["tests"]
    pd={t:dur(r) for t,r in pr.items() if not t.startswith(BP)}
    col=[t for t in ld(A/f"collect_{B}.json")["collected"] if not t.startswith(BP)]
    suite=list(dict.fromkeys(col))
    passes=[ld(A/f"run_w{B}_t{B}_pass{k}.json")["tests"] for k in (1,2)]
    real={t:statistics.mean([dur(p[t]) for p in passes if t in p]) for t in suite}
    data[(P,B)]=(pd,suite,real)
def est_fn(pd,suite,rule):
    byf={}
    for t,d in pd.items(): byf.setdefault(fil(t),[]).append(d)
    allv=list(pd.values())
    e={}
    for t in suite:
        if t in pd: e[t]=pd[t]; continue
        f=byf.get(fil(t),[])
        e[t]=rule(f,allv)
    return e
def plan(suite,est,b):
    pos={t:i for i,t in enumerate(suite)}
    ch=[];s=0
    for t in sorted(suite,key=lambda t:(est[t],pos[t])):
        if s+est[t]<=b: ch.append(t); s+=est[t]
    return ch
rules={
 "median":lambda f,a: statistics.median(f) if len(f)>=3 else statistics.median(a),
 "mean":lambda f,a: statistics.mean(f) if len(f)>=3 else statistics.mean(a),
 "q75":lambda f,a: q(f,.75) if len(f)>=3 else q(a,.75),
 "q90":lambda f,a: q(f,.9) if len(f)>=3 else q(a,.9),
 "q90_newfile_mean":lambda f,a: q(f,.9) if len(f)>=3 else statistics.mean(a),
 "mean_newfile_q90":lambda f,a: statistics.mean(f) if len(f)>=3 else q(a,.9),
 "max_mean":lambda f,a: max(statistics.mean(f) if f else 0, statistics.mean(a)),
 "fmax":lambda f,a: max(f) if len(f)>=3 else max(a),
 "mean_x2":lambda f,a: 2*(statistics.mean(f) if len(f)>=3 else statistics.mean(a)),
}
for name,rule in rules.items():
    row=[]
    for k,(pd,suite,real) in data.items():
        e=est_fn(pd,suite,rule); tot=sum(e.values()); tr=sum(real.values())
        s=[]
        for f in (0.05,0.25):
            b=f*tot; p=plan(suite,e,b); s.append(sum(real[t] for t in p)/b)
        row.append((s[0],s[1],tot/tr-1))
    m5=statistics.mean(r[0] for r in row); x5=max(r[0] for r in row)
    m25=statistics.mean(r[1] for r in row); x25=max(r[1] for r in row)
    print(f"{name:18s} 5%: {m5:.2f}/{x5:.2f} 25%: {m25:.2f}/{x25:.2f} P2:",[round(r[2],2) for r in row], " per-pair 5%",[round(r[0],2) for r in row]," 25%",[round(r[1],2) for r in row])
print("----- decomposition 25%, mean rule")
for k,(pd,suite,real) in data.items():
    e=est_fn(pd,suite,rules["mean"]); tot=sum(e.values()); 
    for f in (0.05,0.25):
        b=f*tot; p=plan(suite,e,b)
        seen=[t for t in p if t in pd]; un=[t for t in p if t not in pd]
        print(k,f, "budget %.1f"%b, "seen real/b %.2f est/b %.2f"%(sum(real[t] for t in seen)/b, sum(e[t] for t in seen)/b), "unseen n=%d real/b %.2f est/b %.2f"%(len(un),sum(real[t] for t in un)/b,sum(e[t] for t in un)/b))
    # top files of unseen overspend
    un=[t for t in suite if t not in pd]
    byf={}
    for t in un: byf.setdefault(fil(t),[0,0,0]); byf[fil(t)][0]+=1; byf[fil(t)][1]+=e[t]; byf[fil(t)][2]+=real[t]
    top=sorted(byf.items(),key=lambda kv:-kv[1][2])[:4]
    print("   unseen n",len(un),"tot est %.1f real %.1f"%(sum(e[t] for t in un),sum(real[t] for t in un)), [(f.split('/')[-1],v[0],round(v[1],2),round(v[2],2)) for f,v in top])
