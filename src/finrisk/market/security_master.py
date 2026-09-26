from __future__ import annotations
import pandas as pd

REQUIRED_SECURITY_MASTER={"security_id","issuer_id","security_name","valid_from","valid_to","source","source_identifier"}

def validate_security_master(df:pd.DataFrame)->dict:
    missing=REQUIRED_SECURITY_MASTER-set(df.columns)
    if missing:raise ValueError(f"Missing security-master fields: {sorted(missing)}")
    x=df.copy();x["valid_from"]=pd.to_datetime(x["valid_from"]);x["valid_to"]=pd.to_datetime(x["valid_to"])
    if (x["valid_to"]<x["valid_from"]).any():raise ValueError("Security validity interval ends before it starts")
    duplicates=int(x.duplicated(["security_id","valid_from","valid_to","source_identifier"]).sum())
    if duplicates:raise ValueError("Duplicate security-master evidence")
    overlaps=0
    for sid,g in x.sort_values("valid_from").groupby("security_id"):
        prev=None
        for _,r in g.iterrows():
            if prev is not None and r["valid_from"]<=prev:overlaps+=1
            prev=max(prev,r["valid_to"]) if prev is not None else r["valid_to"]
    return {"rows":int(len(x)),"securities":int(x["security_id"].nunique()),"issuers":int(x["issuer_id"].nunique()),
            "overlapping_intervals":overlaps}
