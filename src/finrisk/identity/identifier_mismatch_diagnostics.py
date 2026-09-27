from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def mismatch_diagnostics(intersection:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    required={"cik","identifier","candidate_cusip","identifier_match"}
    missing=required-set(intersection.columns)
    if missing:
        raise ValueError(f"Missing intersection fields: {sorted(missing)}")
    d=intersection.copy()
    d["sec_cusip"]=d["identifier"].fillna("").astype(str).str.strip().str.upper()
    d["candidate_cusip_norm"]=d["candidate_cusip"].fillna("").astype(str).str.strip().str.upper()
    usable=d["candidate_cusip_norm"].str.len().eq(9)&d["sec_cusip"].str.len().eq(9)
    d["relationship"]="unusable"
    d.loc[usable,"relationship"]="different_issuer_root"
    d.loc[usable & d["sec_cusip"].str[:6].eq(d["candidate_cusip_norm"].str[:6]),"relationship"]="same_issuer_root_different_issue"
    d.loc[usable & d["sec_cusip"].str[:8].eq(d["candidate_cusip_norm"].str[:8]),"relationship"]="same_security_body_check_digit_difference"
    d.loc[usable & d["sec_cusip"].eq(d["candidate_cusip_norm"]),"relationship"]="exact"
    report={
        "rows":int(len(d)),
        "issuers":int(d["cik"].nunique()),
        "by_relationship":{k:int(v) for k,v in d["relationship"].value_counts().to_dict().items()},
        "issuers_by_relationship":{k:int(v) for k,v in d.groupby("relationship")["cik"].nunique().to_dict().items()},
    }
    return d,report

def write_mismatch_diagnostics(intersection:pd.DataFrame,out_dir:Path)->dict:
    d,r=mismatch_diagnostics(intersection)
    out_dir.mkdir(parents=True,exist_ok=True)
    d.to_parquet(out_dir/"identifier_mismatch_diagnostics.parquet",index=False)
    (out_dir/"identifier_mismatch_diagnostics.json").write_text(json.dumps(r,indent=2,sort_keys=True))
    return r
