from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from finrisk.identity.identifier_corroboration import valid_cusip

@dataclass(frozen=True)
class ColumnBounds:
    cusip_left:float
    issuer_left:float
    description_left:float
    status_left:float

# Verified against the official list PDFs for 2009Q4/2010Q2/2011Q3/2015Q1/2020Q1
# (612x792pt media box, 1in left margin). Observed word x0 positions on a data row:
#   cusip issuer root  6 chars  x0 ~= 72.8
#   cusip issue number 2 chars  x0 ~= 115.7
#   cusip check digit  1 char   x0 ~= 135.1
#   "*" added marker             x0 ~= 150.1
#   issuer name (truncates ~28 chars)  x0 from 167.4
#   issuer description           x0 ~= 350.5
#   status ("ADDED", ...)        x0 ~= 468.2
# The CUSIP spans THREE words, so issuer_left must sit above 135.1 -- not 115,
# which clipped the issue-number word by 0.7pt and left a 6-character CUSIP that
# could never pass valid_cusip, yielding zero parsed rows on every page.
OFFICIAL_LIST_BOUNDS=ColumnBounds(cusip_left=70.0,issuer_left=148.0,description_left=348.0,status_left=462.0)

# Page 0 of each list is the ABA/CUSIP Global Services copyright notice, whose
# prose lines otherwise reach the row parser.
COPYRIGHT_COVER_PAGES=1

def _join(words): return " ".join(str(w["text"]) for w in sorted(words,key=lambda z:z["x0"])).strip()

def parse_page_words(words:list[dict],bounds:ColumnBounds,y_tolerance:float=2.5)->pd.DataFrame:
    required={"text","x0","x1","top"}
    if any(required-set(w) for w in words): raise ValueError("Positional words require text/x0/x1/top")
    ordered=sorted(words,key=lambda w:(float(w["top"]),float(w["x0"])))
    lines=[]
    for w in ordered:
        y=float(w["top"])
        if not lines or abs(y-lines[-1][0])>y_tolerance: lines.append([y,[w]])
        else: lines[-1][1].append(w)
    rows=[]
    for _,line in lines:
        cus=_join([w for w in line if bounds.cusip_left<=float(w["x0"])<bounds.issuer_left]).replace(" ","")
        issuer_words=[w for w in line if bounds.issuer_left<=float(w["x0"])<bounds.description_left]
        desc_words=[w for w in line if bounds.description_left<=float(w["x0"])<bounds.status_left]
        status_words=[w for w in line if float(w["x0"])>=bounds.status_left]
        issuer=_join(issuer_words);desc=_join(desc_words);status=_join(status_words)
        added=issuer.startswith("*")
        if added: issuer=issuer[1:].strip()
        if not valid_cusip(cus): continue
        if desc.upper() in {"CALL","PUT"}: continue
        if not issuer: continue
        rows.append({"cusip":cus,"issuer_name":issuer,"issuer_description":desc,"status":status,"added_marker":added})
    return pd.DataFrame(rows).drop_duplicates()

def validate_page_population(frame:pd.DataFrame,min_rows:int)->None:
    if len(frame)<min_rows: raise ValueError(f"Parsed page below row-count floor: {len(frame)} < {min_rows}")


def page_fidelity_report(words:list[dict],bounds:ColumnBounds,y_tolerance:float=2.5)->dict:
    """Count candidate rows without dropping any, so fidelity can be asserted.

    parse_page_words filters invalid CUSIPs and CALL/PUT rows, which makes a bad
    bounds guess indistinguishable from a genuinely empty page. This reports the
    pre-filter population instead.

    Equity rows are expected to be 100% check-digit valid: the SEC derives the
    CALL/PUT pseudo-CUSIPs by substituting 90/95 into the issue field without
    recomputing the check digit, so option rows fail validation at chance rate
    and equity rows do not.
    """
    ordered=sorted(words,key=lambda w:(float(w["top"]),float(w["x0"])))
    lines=[]
    for w in ordered:
        y=float(w["top"])
        if not lines or abs(y-lines[-1][0])>y_tolerance: lines.append([y,[w]])
        else: lines[-1][1].append(w)
    candidates=options=equity=equity_valid=0
    for _,line in lines:
        cus=_join([w for w in line if bounds.cusip_left<=float(w["x0"])<bounds.issuer_left]).replace(" ","")
        if len(cus)!=9: continue
        candidates+=1
        desc=_join([w for w in line if bounds.description_left<=float(w["x0"])<bounds.status_left])
        if desc.upper() in {"CALL","PUT"}:
            options+=1
            continue
        equity+=1
        if valid_cusip(cus): equity_valid+=1
    return {"candidate_rows":candidates,"option_rows":options,"equity_rows":equity,
            "equity_cusip_valid":equity_valid,
            "equity_valid_rate":(equity_valid/equity) if equity else 0.0}


def assert_equity_cusip_fidelity(report:dict,vintage:str)->None:
    """Fail closed: every equity row must carry a check-digit-valid CUSIP."""
    if not report["equity_rows"]:
        raise ValueError(f"No equity rows parsed for {vintage}: {report}")
    if report["equity_cusip_valid"]!=report["equity_rows"]:
        raise ValueError(f"Equity CUSIP fidelity below 100% for {vintage}: {report}")
