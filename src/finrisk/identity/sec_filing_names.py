from __future__ import annotations
import pandas as pd

def filing_name_history(submissions:dict,cik:str)->pd.DataFrame:
    recent=submissions.get("filings",{}).get("recent",{})
    dates=recent.get("filingDate",[]);accessions=recent.get("accessionNumber",[])
    current=submissions.get("name")
    rows=[]
    for d,a in zip(dates,accessions):
        rows.append({"cik":str(cik).zfill(10),"filing_date":d,"accession":a,"sec_name":current,
                     "evidence_type":"submissions_current_name"})
    for f in submissions.get("formerNames",[]) or []:
        rows.append({"cik":str(cik).zfill(10),"filing_date":f.get("to"),"accession":None,"sec_name":f.get("name"),
                     "evidence_type":"former_name_period_end","from_date":f.get("from"),"to_date":f.get("to")})
    return pd.DataFrame(rows)
