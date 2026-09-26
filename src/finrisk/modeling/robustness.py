from __future__ import annotations
import pandas as pd
from finrisk.modeling.evaluation import rare_event_metrics

def yearly_metrics(frame:pd.DataFrame,label_col="distress_12m",score_col="score")->dict:
    x=frame.copy();x["filed"]=pd.to_datetime(x["filed"]);out={}
    for year,g in x.groupby(x["filed"].dt.year):
        if g[label_col].nunique()<2:
            out[str(year)]={"rows":len(g),"positives":int(g[label_col].sum()),"status":"insufficient_classes"}
        else:out[str(year)]=rare_event_metrics(g[label_col],g[score_col])
    return out

def subgroup_metrics(frame:pd.DataFrame,group_col:str,label_col="distress_12m",score_col="score",min_rows=500)->dict:
    out={}
    for value,g in frame.groupby(group_col,dropna=False):
        key=str(value)
        if len(g)<min_rows or g[label_col].nunique()<2:
            out[key]={"rows":len(g),"positives":int(g[label_col].sum()),"status":"insufficient_support"}
        else:out[key]=rare_event_metrics(g[label_col],g[score_col])
    return out
