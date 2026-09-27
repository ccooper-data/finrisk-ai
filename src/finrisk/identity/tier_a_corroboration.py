from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def corroboration_candidates(frame:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    if frame.empty:
        return pd.DataFrame(),{"targets":0,"candidate_identifiers":0,"multi_document":0,"multi_accession":0}
    x=frame[frame["common_equity_context"].fillna(False)].copy()
    key=["cik","identifier_type","identifier","candidate_security_id"]
    rows=[]
    for vals,g in x.groupby(key,dropna=False):
        cik,kind,identifier,security=vals
        docs=int(g["document_sha256"].nunique());accessions=int(g["accession"].nunique())
        rows.append({"cik":cik,"candidate_security_id":security,"identifier_type":kind,"identifier":identifier,
                     "evidence_rows":len(g),"independent_documents":docs,"independent_accessions":accessions,
                     "first_filing_date":str(g["filing_date"].min()),"last_filing_date":str(g["filing_date"].max()),
                     "corroboration_status":"multi_accession" if accessions>=2 else ("multi_document" if docs>=2 else "single_document"),
                     "acceptance_status":"unreviewed"})
    d=pd.DataFrame(rows)
    report={"targets":int(d["cik"].nunique()) if len(d) else 0,"candidate_identifiers":len(d),
            "multi_document":int(d["independent_documents"].ge(2).sum()) if len(d) else 0,
            "multi_accession":int(d["independent_accessions"].ge(2).sum()) if len(d) else 0,
            "single_document":int(d["independent_documents"].eq(1).sum()) if len(d) else 0}
    return d,report

def write_corroboration(frame:pd.DataFrame,out_dir:Path)->dict:
    d,r=corroboration_candidates(frame);out_dir.mkdir(parents=True,exist_ok=True)
    d.to_parquet(out_dir/"tier_a_corroboration_candidates.parquet",index=False)
    (out_dir/"tier_a_corroboration.json").write_text(json.dumps(r,indent=2,sort_keys=True))
    return r
