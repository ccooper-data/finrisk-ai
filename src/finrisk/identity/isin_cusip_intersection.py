from __future__ import annotations
import json,re
from pathlib import Path
import pandas as pd

ISIN_RE=re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
CUSIP_RE=re.compile(r"^[A-Z0-9*@#]{9}$")

def cusip_from_us_isin(isin:str)->str|None:
    x=str(isin).strip().upper()
    if not ISIN_RE.fullmatch(x) or not x.startswith("US"):return None
    cusip=x[2:11]
    return cusip if CUSIP_RE.fullmatch(cusip) else None

def identifier_intersection(corroboration:pd.DataFrame,targets:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    required={"cik","candidate_security_id","identifier_type","identifier","independent_accessions"}
    missing=required-set(corroboration.columns)
    if missing:raise ValueError(f"Missing corroboration fields: {sorted(missing)}")
    if "isin" not in targets.columns:raise ValueError("Targets must preserve candidate ISIN for identifier intersection")
    t=targets[["cik","top_security_id","isin","target_priority"]].copy()
    t["candidate_cusip"]=t["isin"].map(cusip_from_us_isin)
    c=corroboration[(corroboration["identifier_type"].eq("CUSIP"))&(corroboration["independent_accessions"].ge(2))].copy()
    out=c.merge(t,left_on=["cik","candidate_security_id"],right_on=["cik","top_security_id"],how="left")
    out["identifier_match"]=out["candidate_cusip"].notna() & out["identifier"].astype(str).str.upper().eq(out["candidate_cusip"])
    out["review_status"]="unreviewed"
    report={"multi_accession_cusip_candidates":len(out),"targets":int(out["cik"].nunique()) if len(out) else 0,
            "targets_with_usable_us_isin":int(t["candidate_cusip"].notna().sum()),
            "exact_cusip_matches":int(out["identifier_match"].sum()) if len(out) else 0,
            "targets_with_exact_match":int(out.loc[out["identifier_match"],"cik"].nunique()) if len(out) else 0}
    return out,report

def write_intersection(corroboration:pd.DataFrame,targets:pd.DataFrame,out_dir:Path)->dict:
    d,r=identifier_intersection(corroboration,targets);out_dir.mkdir(parents=True,exist_ok=True)
    d.to_parquet(out_dir/"tier_a_identifier_intersection.parquet",index=False)
    (out_dir/"tier_a_identifier_intersection.json").write_text(json.dumps(r,indent=2,sort_keys=True))
    return r
