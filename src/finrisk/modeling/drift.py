from __future__ import annotations
import numpy as np,pandas as pd

def population_stability_index(reference,current,bins=10)->float:
    ref=pd.Series(reference).dropna();cur=pd.Series(current).dropna()
    if ref.empty or cur.empty:return float("nan")
    edges=np.unique(np.quantile(ref,np.linspace(0,1,bins+1)))
    if len(edges)<3:return 0.0
    edges[0],edges[-1]=-np.inf,np.inf
    a=np.histogram(ref,bins=edges)[0]/len(ref);b=np.histogram(cur,bins=edges)[0]/len(cur)
    eps=1e-6;a=np.clip(a,eps,None);b=np.clip(b,eps,None)
    return float(np.sum((b-a)*np.log(b/a)))

def feature_drift(reference:pd.DataFrame,current:pd.DataFrame,features:list[str])->dict:
    return {f:{"psi":population_stability_index(reference[f],current[f]),
               "reference_null":float(reference[f].isna().mean()),
               "current_null":float(current[f].isna().mean())} for f in features if f in reference and f in current}
