"""Reviewer check (post-hoc, not in the paper): run selectors under the FROZEN budgets with finite budget_s, as the methodology describes,
and report detection, labelled cost actually spent, and tests selected. Run: PYTHONPATH=src python scripts/budgeted_check.py"""
import json, numpy as np
from cart.metrics.evaluate import _build_payloads
from cart.selectors.registry_scaleup import SELECTORS_SCALEUP as S
from cart.selectors.cost_model import expected_cost
pay=_build_payloads("data_scaleup",None,"all")
T=63.16
for tier,b in [("pr",0.05*T),("nightly",0.5*T)]:
    res={n:[] for n in list(S)}; used={n:[] for n in S}; n_sel={n:[] for n in S}
    for p in pay:
        for n,sel in S.items():
            sd=range(20) if n=="random" else [0]
            hs=[];us=[];ns=[]
            for sdv in sd:
                chosen=sel(p["ctx"],p["event_id"],b,seed=sdv)
                hs.append(any(p["detects"].get(t,False) for t in chosen))
                us.append(sum(p["cost"][t] for t in chosen if t in p["cost"])); ns.append(len(chosen))
            res[n].append(np.mean(hs)); used[n].append(np.mean(us)); n_sel[n].append(np.mean(ns))
    print(tier,round(b,2),{n:(round(np.mean(v),3),round(np.mean(used[n])),round(np.mean(n_sel[n]))) for n,v in res.items()})
