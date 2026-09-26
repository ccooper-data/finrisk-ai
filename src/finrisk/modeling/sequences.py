from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from finrisk.modeling.baseline import TemporalSplit

SEQUENCE_FEATURES=[
    "assets","liabilities","equity","current_assets","current_liabilities","cash",
    "revenue","net_income","operating_income","operating_cash_flow",
    "current_ratio","liabilities_to_assets","liabilities_to_equity","roa","roe",
    "operating_margin","net_margin","cash_to_liabilities",
]

@dataclass(frozen=True)
class SequenceConfig:
    lookback:int=8
    min_history:int=2

def add_change_features(frame:pd.DataFrame,features:list[str])->tuple[pd.DataFrame,list[str]]:
    out=frame.sort_values(["cik","filed","adsh"]).copy();derived=[]
    for col in features:
        if col not in out:continue
        g=out.groupby("cik",sort=False)[col]
        qoq=f"{col}__qoq";yoy=f"{col}__yoy"
        out[qoq]=g.pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)
        out[yoy]=g.pct_change(4,fill_method=None).replace([np.inf,-np.inf],np.nan)
        derived.extend([qoq,yoy])
    return out,derived

def build_sequence_arrays(frame:pd.DataFrame,split:TemporalSplit=TemporalSplit(),config:SequenceConfig=SequenceConfig()):
    x=frame.copy();x["filed"]=pd.to_datetime(x["filed"])
    base=[c for c in SEQUENCE_FEATURES if c in x.columns]
    x,derived=add_change_features(x,base);features=base+derived
    train_mask=x["filed"]<=pd.Timestamp(split.train_end)
    observed=[col for col in features if x.loc[train_mask,col].notna().any()]
    features=observed
    imputer=SimpleImputer(strategy="median",add_indicator=False);scaler=StandardScaler()
    train_matrix=imputer.fit_transform(x.loc[train_mask,features])
    scaler.fit(train_matrix)
    transformed=scaler.transform(imputer.transform(x[features])).astype("float32")
    x["_row"]=np.arange(len(x));seqs=[];labels=[];dates=[];ciks=[];lengths=[]
    for cik,g in x.groupby("cik",sort=False):
        g=g.sort_values("filed")
        idx=g["_row"].to_numpy()
        for pos,row_idx in enumerate(idx):
            start=max(0,pos-config.lookback+1);hist=idx[start:pos+1]
            if len(hist)<config.min_history:continue
            seq=np.zeros((config.lookback,len(features)),dtype="float32")
            seq[-len(hist):]=transformed[hist]
            seqs.append(seq);lengths.append(len(hist));labels.append(int(x.iloc[row_idx]["distress_12m"]))
            dates.append(x.iloc[row_idx]["filed"]);ciks.append(str(cik))
    sequences=np.stack(seqs) if seqs else np.empty((0,config.lookback,len(features)),dtype="float32")
    labels=np.asarray(labels,dtype="float32");dates=pd.to_datetime(dates)
    masks={"train":dates<=pd.Timestamp(split.train_end),
           "validation":(dates>pd.Timestamp(split.train_end))&(dates<=pd.Timestamp(split.validation_end)),
           "test":dates>pd.Timestamp(split.validation_end)}
    meta={"features":features,"lookback":config.lookback,"min_history":config.min_history,
          "rows":int(len(labels)),"companies":int(pd.Series(ciks).nunique()),
          "split_rows":{k:int(v.sum()) for k,v in masks.items()},
          "split_positives":{k:int(labels[v].sum()) for k,v in masks.items()}}
    return sequences,labels,masks,np.asarray(lengths),meta
