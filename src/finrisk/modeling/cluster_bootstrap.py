"""Paired issuer-cluster uncertainty for an already-fitted model/calibrator."""
from __future__ import annotations
import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

def _losses(y,p):
    return {"brier":float(brier_score_loss(y,p)),
            "log_loss":float(log_loss(y,p,labels=[0,1]))}

def paired_cik_cluster_bootstrap(y,p_model,p_baseline,ciks,*,replicates=10000,seed=42):
    y=np.asarray(y,dtype=int);pm=np.asarray(p_model,dtype=float);pb=np.asarray(p_baseline,dtype=float)
    c=np.asarray(ciks,dtype=str)
    if not(len(y)==len(pm)==len(pb)==len(c)) or not len(y):raise ValueError("aligned nonempty arrays required")
    if np.any(c=="unavailable") or np.any(c==""):raise ValueError("complete usable CIK coverage required")
    unique,inv=np.unique(c,return_inverse=True)
    if len(unique)<2:raise ValueError("at least two issuer clusters required")
    groups=[np.flatnonzero(inv==i) for i in range(len(unique))]
    point_m=_losses(y,pm);point_b=_losses(y,pb)
    point={k:point_b[k]-point_m[k] for k in point_m}
    rng=np.random.default_rng(seed);draws={k:np.empty(replicates) for k in point}
    for r in range(replicates):
        sampled=rng.integers(0,len(groups),len(groups))
        idx=np.concatenate([groups[i] for i in sampled])
        lm=_losses(y[idx],pm[idx]);lb=_losses(y[idx],pb[idx])
        for k in draws:draws[k][r]=lb[k]-lm[k]
    metrics={}
    for k,v in draws.items():
        lo,hi=np.quantile(v,[.025,.975])
        metrics[k]={"baseline_minus_model":point[k],"interval_95":[float(lo),float(hi)],
                    "replicates_model_better":int(np.sum(v>0)),
                    "replicates_model_not_better":int(np.sum(v<=0))}
    return {"method":"paired_cik_cluster_bootstrap","seed":seed,"replicates":replicates,
            "test_rows":int(len(y)),"unique_test_ciks":int(len(unique)),
            "comparison":"validation-fitted constant minus calibrated model; positive favors model",
            "metrics":metrics,
            "scope":{"conditional_on_fitted_model_and_calibrator":True,
                     "includes_retraining_uncertainty":False,
                     "includes_calibrator_refit_uncertainty":False,
                     "addresses_cross_issuer_macro_dependence":False,
                     "population_generalization_interval":False}}
