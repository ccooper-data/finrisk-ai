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
