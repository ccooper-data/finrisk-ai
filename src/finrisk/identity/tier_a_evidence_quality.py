from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def evidence_quality(frame:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    if frame.empty:
        return frame.copy(),{"rows":0,"targets":0,"common_equity_rows":0,"unique_identifiers":0,"duplicate_rate":None}
    key=["cik","identifier_type","identifier"]
    x=frame.copy()
    x["duplicate_identifier_evidence"]=x.duplicated(key,keep=False)
    per=x.groupby("cik").agg(
        evidence_rows=("identifier","size"),
        unique_identifiers=("identifier","nunique"),
        common_equity_rows=("common_equity_context","sum"),
        documents=("document_sha256","nunique"),
    ).reset_index()
    unique=x.drop_duplicates(key)
    report={"rows":len(x),"targets":int(x["cik"].nunique()),
            "common_equity_rows":int(x["common_equity_context"].sum()),
            "unique_identifiers":int(len(unique)),
            "targets_with_common_equity":int(per["common_equity_rows"].gt(0).sum()),
            "duplicate_rate":float(x["duplicate_identifier_evidence"].mean()),
            "identifier_types":{str(k):int(v) for k,v in x["identifier_type"].value_counts().items()},
            "security_contexts":{str(k):int(v) for k,v in x["security_context"].value_counts().items()}}
    return per,report

def write_quality(frame:pd.DataFrame,out_dir:Path)->dict:
    per,report=evidence_quality(frame);out_dir.mkdir(parents=True,exist_ok=True)
    per.to_parquet(out_dir/"tier_a_evidence_quality_by_target.parquet",index=False)
    (out_dir/"tier_a_evidence_quality.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
