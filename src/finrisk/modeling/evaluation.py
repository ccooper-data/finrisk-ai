from __future__ import annotations
import numpy as np
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss,precision_recall_curve

def rare_event_metrics(y,p,alert_rates=(.001,.005,.01,.025,.05)):
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float);n=len(y);order=np.argsort(-p)
    out={"rows":n,"positives":int(y.sum()),"prevalence":float(y.mean()),
         "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
         "brier":float(brier_score_loss(y,p))}
    alerts={}
    for rate in alert_rates:
        k=max(1,int(np.ceil(n*rate)));idx=order[:k];tp=int(y[idx].sum())
        alerts[str(rate)]={"k":k,"precision":tp/k,"recall":tp/max(1,int(y.sum())),
                           "lift":(tp/k)/max(y.mean(),1e-12)}
    out["alert_rates"]=alerts
    precision,recall,thresholds=precision_recall_curve(y,p)
    f1=2*precision*recall/np.maximum(precision+recall,1e-12);i=int(np.nanargmax(f1))
    out["best_f1"]={"f1":float(f1[i]),"precision":float(precision[i]),"recall":float(recall[i]),
                    "threshold":float(thresholds[i]) if i<len(thresholds) else 1.0}
    return out
