from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from finrisk.features.context import macro_features,MACRO_FEATURES
from finrisk.modeling.baseline import FEATURES,temporal_split

def attach_macro(frame:pd.DataFrame,macro:pd.DataFrame)->pd.DataFrame:
    f=frame.copy();f["filed"]=pd.to_datetime(f["filed"])
    m=macro_features(macro.copy()).sort_values("date")
    cols=["date"]+[c for c in MACRO_FEATURES if c in m.columns]
    return pd.merge_asof(f.sort_values("filed"),m[cols],left_on="filed",right_on="date",direction="backward").sort_index()

def _fit_eval(frame,features):
    tr,va,te=temporal_split(frame);imp=SimpleImputer(strategy="median",add_indicator=True)
    x=imp.fit_transform(tr[features]);y=tr["distress_12m"].astype(int).to_numpy()
    w=np.where(y==1,(1-y.mean())/y.mean(),1.)
    model=HistGradientBoostingClassifier(learning_rate=.05,max_iter=300,max_leaf_nodes=31,min_samples_leaf=40,
        l2_regularization=1.,early_stopping=True,validation_fraction=.15,n_iter_no_change=25,random_state=42)
    model.fit(x,y,sample_weight=w);out={}
    for name,p in [("train",tr),("validation",va),("test",te)]:
        yy=p["distress_12m"].astype(int).to_numpy();prob=model.predict_proba(imp.transform(p[features]))[:,1]
        out[name]={"rows":len(yy),"positives":int(yy.sum()),"pr_auc":float(average_precision_score(yy,prob)),
                   "roc_auc":float(roc_auc_score(yy,prob)),"brier":float(brier_score_loss(yy,prob))}
    return out

def run_macro_ablation(cohort_path:Path,macro_path:Path,out_dir:Path):
    cohort=pd.read_parquet(cohort_path);macro=pd.read_parquet(macro_path);joined=attach_macro(cohort,macro)
    financial=[c for c in FEATURES if c in joined]
    context=[c for c in MACRO_FEATURES if c in joined]
    evidence={"status":"exploratory_current_vintage","warning":"FRED current historical values may include later revisions; not promoted as vintage-safe.",
              "financial_only":_fit_eval(joined,financial),"financial_plus_macro":_fit_eval(joined,financial+context),
              "macro_features":context}
    out_dir.mkdir(parents=True,exist_ok=True)
    (out_dir/"macro_ablation.json").write_text(json.dumps(evidence,indent=2,sort_keys=True));return evidence
