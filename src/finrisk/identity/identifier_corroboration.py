from __future__ import annotations
import re,pandas as pd

CUSIP_RE=re.compile(r"(?<![A-Z0-9])([0-9A-Z*@#]{8}[0-9A-Z*@#])(?![A-Z0-9])")
ISIN_RE=re.compile(r"(?<![A-Z0-9])([A-Z]{2}[A-Z0-9]{9}[0-9])(?![A-Z0-9])")

def extract_identifiers(text:str)->dict:
    s=(text or "").upper()
    return {"cusips":sorted(set(CUSIP_RE.findall(s))),"isins":sorted(set(ISIN_RE.findall(s)))}

def corroborate_candidate(candidate_isin:str|None,evidence_isins:list[str],evidence_cusips:list[str])->dict:
    isin=(candidate_isin or "").strip().upper()
    exact_isin=bool(isin and isin in {x.upper() for x in evidence_isins})
    # US/CA ISINs embed the 9-character national security identifier after country code.
    embedded=isin[2:11] if len(isin)==12 else ""
    cusip_match=bool(embedded and embedded in {x.upper() for x in evidence_cusips})
    return {"exact_isin_match":exact_isin,"isin_embedded_cusip_match":cusip_match,
            "identifier_corroborated":exact_isin or cusip_match}

def evidence_table(rows:list[dict])->pd.DataFrame:
    return pd.DataFrame(rows,columns=["cik","accession","filing_date","source","source_identifier","cusips","isins"])
