from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from finrisk.identity.identifier_corroboration import extract_identifiers

PRIORITY_DOC_TYPES=("EX-4","EX-2","10-K","10-Q","8-K")

@dataclass(frozen=True)
class FilingDocument:
    cik:str
    accession:str
    filing_date:str
    document_type:str
    source_url:str
    text:str

def collect_identifier_evidence(documents:list[FilingDocument])->pd.DataFrame:
    rows=[]
    for d in documents:
        if not any(d.document_type.upper().startswith(x) for x in PRIORITY_DOC_TYPES):
            continue
        ids=extract_identifiers(d.text)
        if not ids["cusips"] and not ids["isins"]:
            continue
        rows.append({"cik":d.cik,"accession":d.accession,"filing_date":d.filing_date,
                     "document_type":d.document_type,"source":d.source_url,
                     "cusips":ids["cusips"],"isins":ids["isins"],
                     "review_status":"unreviewed"})
    return pd.DataFrame(rows)

def explode_identifier_evidence(frame:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for _,r in frame.iterrows():
        for kind,col in [("CUSIP","cusips"),("ISIN","isins")]:
            for value in r[col]:
                rows.append({"cik":r["cik"],"accession":r["accession"],"filing_date":r["filing_date"],
                             "document_type":r["document_type"],"source":r["source"],
                             "identifier_type":kind,"identifier":value,"review_status":"unreviewed"})
    return pd.DataFrame(rows)
