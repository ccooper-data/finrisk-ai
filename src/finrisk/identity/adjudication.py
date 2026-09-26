from __future__ import annotations
import pandas as pd

def adjudication_queue(candidates:pd.DataFrame,top_margin:float=.08)->pd.DataFrame:
    if candidates.empty:return candidates.copy()
    rows=[]
    for cik,g in candidates.sort_values("discovery_score",ascending=False).groupby("cik"):
        g=g.reset_index(drop=True);top=float(g.loc[0,"discovery_score"]);second=float(g.loc[1,"discovery_score"]) if len(g)>1 else 0.
        for i,r in g.iterrows():
            x=r.to_dict();x["rank"]=i+1;x["top_margin"]=top-second
            if i==0 and top>=.90 and top-second>=top_margin:x["review_priority"]="high"
            elif i<3:x["review_priority"]="medium"
            else:x["review_priority"]="low"
            x["acceptance_status"]="unreviewed"
            rows.append(x)
    return pd.DataFrame(rows)

def validate_adjudication(frame:pd.DataFrame)->None:
    allowed={"unreviewed","accepted_identifier","rejected","needs_evidence"}
    bad=set(frame["acceptance_status"])-allowed
    if bad:raise ValueError(f"Invalid adjudication statuses: {sorted(bad)}")
