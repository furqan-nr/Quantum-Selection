exec(open('/tmp/pe_scratch/explore.py').read().split('rules={')[0])
import itertools
def stat(xs,s):
    if s=="median": return statistics.median(xs)
    if s=="mean": return statistics.mean(xs)
    if s.startswith("q"): return q(xs,int(s[1:])/100)
    if s=="max": return max(xs)
ins=["median","mean","q75","q90"]
news=["median","mean","q75","q90","q95","fmeans_mean","fmeans_median","fmeans_q75"]
for a,bn in itertools.product(ins,news):
    def rule(f,allv,_cache={}):
        pass
    row=[]
    for k,(pd,suite,real) in data.items():
        byf={}
        for t,d in pd.items(): byf.setdefault(fil(t),[]).append(d)
        allv=list(pd.values())
        fm=[statistics.mean(v) for v in byf.values()]
        if bn.startswith("fmeans"): g=stat(fm,bn.split("_")[1])
        else: g=stat(allv,bn)
        e={}
        for t in suite:
            if t in pd: e[t]=pd[t]; continue
            f=byf.get(fil(t),[])
            e[t]=stat(f,a) if len(f)>=3 else g
        tot=sum(e.values()); tr=sum(real.values()); s=[]
        for fr in (0.05,0.25):
            b=fr*tot; p=plan(suite,e,b); s.append(sum(real[t] for t in p)/b)
        row.append((s[0],s[1],tot/tr-1))
    m5=statistics.mean(r[0] for r in row); x5=max(r[0] for r in row); m25=statistics.mean(r[1] for r in row); x25=max(r[1] for r in row)
    print(f"in={a:6s} new={bn:13s} 5%: {m5:.2f}/{x5:.2f} 25%: {m25:.2f}/{x25:.2f} P2:",[round(r[2],2) for r in row],"25%",[round(r[1],2) for r in row])
