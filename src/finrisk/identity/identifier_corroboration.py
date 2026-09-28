from __future__ import annotations
import re,pandas as pd

CUSIP_LABEL_RE=re.compile(r"\bCUSIP(?:\s+(?:NO\.?|NUMBER))?\s*[:#-]?\s*([0-9A-Z*@#]{9})\b",re.I)
ISIN_LABEL_RE=re.compile(r"\bISIN(?:\s+(?:NO\.?|NUMBER))?\s*[:#-]?\s*([A-Z]{2}[A-Z0-9]{9}[0-9])\b",re.I)
ISO_COUNTRY_CODES={"US","CA","GB","DE","FR","NL","IE","LU","CH","JP","AU","NZ","SE","NO","DK","FI","BE","AT","ES","IT","PT","GR","PL","CZ","HU","RO","BG","HR","SI","SK","EE","LV","LT","IS","LI","MX","BR","AR","CL","CO","PE","UY","ZA","IL","SA","AE","QA","KW","BH","IN","CN","HK","SG","KR","TW","TH","MY","ID","PH","VN","TR"}

def _cusip_char_value(c:str)->int|None:
    if c.isdigit():return int(c)
    if "A"<=c<="Z":return ord(c)-ord("A")+10
    return {"*":36,"@":37,"#":38}.get(c)

def valid_cusip(value:str)->bool:
    s=str(value).strip().upper()
    if len(s)!=9:return False
    vals=[_cusip_char_value(c) for c in s]
    if any(v is None for v in vals) or not s[8].isdigit():return False
    total=0
    for i,v in enumerate(vals[:8]):
        n=v*(2 if i%2 else 1);total+=n//10+n%10
    return int(s[8])==(10-total%10)%10

def _isin_char_digits(c:str)->str:
    return c if c.isdigit() else str(ord(c)-ord("A")+10)

def valid_isin(value:str)->bool:
    s=str(value).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]",s) or s[:2] not in ISO_COUNTRY_CODES:return False
    digits="".join(_isin_char_digits(c) for c in s)
    total=0
    for i,ch in enumerate(reversed(digits)):
        n=int(ch)*(2 if i%2 else 1);total+=n//10+n%10
    return total%10==0

def extract_identifiers(text:str)->dict:
    s=text or ""
    cusips=sorted({m.group(1).upper() for m in CUSIP_LABEL_RE.finditer(s) if valid_cusip(m.group(1))})
    isins=sorted({m.group(1).upper() for m in ISIN_LABEL_RE.finditer(s) if valid_isin(m.group(1))})
    return {"cusips":cusips,"isins":isins}

def corroborate_candidate(candidate_isin:str|None,evidence_isins:list[str],evidence_cusips:list[str])->dict:
    isin=(candidate_isin or "").strip().upper()
    valid_evidence_isins={x.upper() for x in evidence_isins if valid_isin(x)}
    valid_evidence_cusips={x.upper() for x in evidence_cusips if valid_cusip(x)}
    exact_isin=bool(valid_isin(isin) and isin in valid_evidence_isins)
    embedded=isin[2:11] if valid_isin(isin) and isin[:2] in {"US","CA"} else ""
    cusip_match=bool(embedded and valid_cusip(embedded) and embedded in valid_evidence_cusips)
    return {"exact_isin_match":exact_isin,"isin_embedded_cusip_match":cusip_match,
            "identifier_corroborated":exact_isin or cusip_match}

def evidence_table(rows:list[dict])->pd.DataFrame:
    return pd.DataFrame(rows,columns=["cik","accession","filing_date","source","source_identifier","cusips","isins"])
