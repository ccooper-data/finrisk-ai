from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "current_ratio","liabilities_to_assets","liabilities_to_equity","roa","roe",
    "operating_margin","net_margin","cash_to_liabilities",
]

@dataclass(frozen=True)
class TemporalSplit:
    train_end: str = "2020-12-31"
    validation_end: str = "2022-12-31"

def temporal_split(frame: pd.DataFrame, split: TemporalSplit = TemporalSplit()):
    x=frame.copy()
    x["filed"]=pd.to_datetime(x["filed"])
    train=x[x["filed"]<=pd.Timestamp(split.train_end)].copy()
    validation=x[(x["filed"]>pd.Timestamp(split.train_end)) & (x["filed"]<=pd.Timestamp(split.validation_end))].copy()
    test=x[x["filed"]>pd.Timestamp(split.validation_end)].copy()
    if min(map(len,(train,validation,test)))==0:
        raise ValueError("Temporal train/validation/test partitions must all be nonempty")
    if train["filed"].max() >= validation["filed"].min() or validation["filed"].max() >= test["filed"].min():
        raise ValueError("Temporal partitions overlap")
    return train,validation,test

def _metrics(y,p):
    return {
        "rows":int(len(y)),
        "positives":int(np.sum(y)),
        "prevalence":float(np.mean(y)),
        "pr_auc":float(average_precision_score(y,p)),
        "roc_auc":float(roc_auc_score(y,p)),
        "brier":float(brier_score_loss(y,p)),
    }

def train_logistic_baseline(frame: pd.DataFrame, split: TemporalSplit = TemporalSplit()):
    train,val,test=temporal_split(frame,split)
    features=[c for c in FEATURES if c in frame.columns]
    if not features: raise ValueError("No baseline features available")
    pipe=Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("scale",StandardScaler()),
        ("model",LogisticRegression(max_iter=1000,class_weight="balanced",random_state=42)),
    ])
    pipe.fit(train[features],train["distress_12m"].astype(int))
    results={}
    for name,part in [("train",train),("validation",val),("test",test)]:
        p=pipe.predict_proba(part[features])[:,1]
        results[name]=_metrics(part["distress_12m"].astype(int).to_numpy(),p)
    return pipe,results,{"features":features,"train_end":split.train_end,"validation_end":split.validation_end}

def run_baseline(cohort_path: Path, out_dir: Path):
    frame=pd.read_parquet(cohort_path)
    model,metrics,config=train_logistic_baseline(frame)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"logistic_regression","metrics":metrics,"config":config}
    (out_dir/"baseline_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    return evidence
