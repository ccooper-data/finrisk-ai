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

def _relationship(sec:pd.Series,candidate:pd.Series)->pd.Series:
    a=sec.fillna("").astype(str).str.strip().str.upper()
    b=candidate.fillna("").astype(str).str.strip().str.upper()
    usable=a.str.len().eq(9)&b.str.len().eq(9)
    r=pd.Series("unusable",index=a.index,dtype="object")
    r.loc[usable]="different_issuer_root"
    r.loc[usable&a.str[:6].eq(b.str[:6])]="same_issuer_root_different_issue"
    r.loc[usable&a.str[:8].eq(b.str[:8])]="same_security_body_check_digit_difference"
    r.loc[usable&a.eq(b)]="exact"
    return r

def identifier_intersection(corroboration:pd.DataFrame,targets:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    required={"cik","candidate_security_id","identifier_type","identifier","independent_accessions"}
    missing=required-set(corroboration.columns)
    if missing:raise ValueError(f"Missing corroboration fields: {sorted(missing)}")
    if "isin" not in targets.columns:raise ValueError("Targets must preserve candidate ISIN for identifier intersection")
    t=targets[["cik","top_security_id","isin","target_priority"]].copy()
    t["candidate_cusip"]=t["isin"].map(cusip_from_us_isin)
    c=corroboration[(corroboration["identifier_type"].eq("CUSIP"))&(corroboration["independent_accessions"].ge(2))].copy()
    out=c.merge(t,left_on=["cik","candidate_security_id"],right_on=["cik","top_security_id"],how="left")
    out["identifier_relationship"]=_relationship(out["identifier"],out["candidate_cusip"])
    out["identifier_match"]=out["identifier_relationship"].eq("exact")
    out["review_status"]="unreviewed"
    report={"multi_accession_cusip_candidates":len(out),"targets":int(out["cik"].nunique()) if len(out) else 0,
            "targets_with_usable_us_isin":int(t["candidate_cusip"].notna().sum()),
            "exact_cusip_matches":int(out["identifier_match"].sum()) if len(out) else 0,
            "targets_with_exact_match":int(out.loc[out["identifier_match"],"cik"].nunique()) if len(out) else 0,
            "relationship_counts":{k:int(v) for k,v in out["identifier_relationship"].value_counts().to_dict().items()},
            "issuers_by_relationship":{k:int(v) for k,v in out.groupby("identifier_relationship")["cik"].nunique().to_dict().items()}}
    return out,report

def write_intersection(corroboration:pd.DataFrame,targets:pd.DataFrame,out_dir:Path)->dict:
    d,r=identifier_intersection(corroboration,targets);out_dir.mkdir(parents=True,exist_ok=True)
    d.to_parquet(out_dir/"tier_a_identifier_intersection.parquet",index=False)
    (out_dir/"tier_a_identifier_intersection.json").write_text(json.dumps(r,indent=2,sort_keys=True))
    return r
