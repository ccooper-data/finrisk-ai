from __future__ import annotations
import pandas as pd

def attach_security_asof(filings:pd.DataFrame,links:pd.DataFrame)->pd.DataFrame:
    f=filings.copy();f["filed"]=pd.to_datetime(f["filed"]);f["_row"]=range(len(f))
    l=links.copy();l["valid_from"]=pd.to_datetime(l["valid_from"]);l["valid_to"]=pd.to_datetime(l["valid_to"])
    pieces=[]
    for cik,g in f.groupby("cik",sort=False):
        cand=l[l["cik"].astype(str).eq(str(cik))]
        for _,r in g.iterrows():
            active=cand[(cand["valid_from"]<=r["filed"])&(cand["valid_to"]>=r["filed"])]
            accepted=active[active["decision"].eq("accepted_identifier")]
            row=r.to_dict()
            if len(accepted)==1:
                row["security_id"]=accepted.iloc[0]["security_id"];row["security_resolution"]="accepted"
            elif len(accepted)>1:
                row["security_id"]=None;row["security_resolution"]="ambiguous"
            else:
                row["security_id"]=None;row["security_resolution"]="unresolved"
            pieces.append(row)
    return pd.DataFrame(pieces).sort_values("_row").drop(columns=["_row"]).reset_index(drop=True)
