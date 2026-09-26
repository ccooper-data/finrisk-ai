from __future__ import annotations
from dataclasses import dataclass
import re,pandas as pd
from finrisk.identity.identifier_corroboration import extract_identifiers

CORE_FORMS={"10-K","10-K/A","10-Q","10-Q/A","8-K","8-K/A"}
EXHIBIT_RE=re.compile(r"^EX-(\d+)(?:\.|$)",re.I)
PRIORITY_EXHIBITS={2,4}

@dataclass(frozen=True)
class FilingDocument:
    cik:str
    accession:str
    filing_date:str
    document_type:str
    source_url:str
    text:str

def is_priority_document(document_type:str)->bool:
    dt=(document_type or "").strip().upper()
    if dt in CORE_FORMS:return True
    m=EXHIBIT_RE.match(dt)
    return bool(m and int(m.group(1)) in PRIORITY_EXHIBITS)

def collect_identifier_evidence(documents:list[FilingDocument])->pd.DataFrame:
    rows=[]
    for d in documents:
        if not is_priority_document(d.document_type):
            continue
        ids=extract_identifiers(d.text)
        if not ids["cusips"] and not ids["isins"]:
            continue
        rows.append({"cik":d.cik,"accession":d.accession,"filing_date":d.filing_date,
                     "document_type":d.document_type,"source":d.source_url,
                     "cusips":ids["cusips"],"isins":ids["isins"],"review_status":"unreviewed"})
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
