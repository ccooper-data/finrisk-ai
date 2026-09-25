from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.impute import SimpleImputer
from finrisk.modeling.baseline import FEATURES, TemporalSplit, temporal_split

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(np.sum(y)),"prevalence":float(np.mean(y)),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_boosted_tree(frame:pd.DataFrame,split:TemporalSplit=TemporalSplit()):
    train,val,test=temporal_split(frame,split)
    features=[c for c in FEATURES if c in frame.columns]
    imputer=SimpleImputer(strategy="median",add_indicator=True)
    x_train=imputer.fit_transform(train[features])
    y_train=train["distress_12m"].astype(int).to_numpy()
    # Preserve ranking pressure on the rare class without altering the held-out population.
    prevalence=float(y_train.mean())
    positive_weight=(1.0-prevalence)/prevalence
    weights=np.where(y_train==1,positive_weight,1.0)
    model=HistGradientBoostingClassifier(
        learning_rate=0.05,max_iter=300,max_leaf_nodes=31,min_samples_leaf=40,
        l2_regularization=1.0,early_stopping=True,validation_fraction=0.15,
        n_iter_no_change=25,random_state=42,
    )
    model.fit(x_train,y_train,sample_weight=weights)
    results={}
    for name,part in [("train",train),("validation",val),("test",test)]:
        p=model.predict_proba(imputer.transform(part[features]))[:,1]
        results[name]=_metrics(part["distress_12m"].astype(int).to_numpy(),p)
    config={"features":features,"train_end":split.train_end,"validation_end":split.validation_end,
            "positive_weight":positive_weight,"iterations":int(model.n_iter_)}
    return model,imputer,results,config

def run_boosted_tree(cohort_path:Path,out_dir:Path):
    frame=pd.read_parquet(cohort_path)
    _,_,metrics,config=train_boosted_tree(frame)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"hist_gradient_boosting","metrics":metrics,"config":config}
    (out_dir/"boosted_tree_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    return evidence
