from __future__ import annotations
import re
import pandas as pd
from finrisk.identity.identifier_corroboration import valid_cusip
from finrisk.identity.resolution import normalize_entity_name

ROW_RE=re.compile(r"^\s*([0-9A-Z*@#]{6})\s+([0-9A-Z*@#]{2})\s+([0-9])\s+(.+?)\s*$")

def parse_official_13f_pdf_text(text:str)->pd.DataFrame:
    rows=[]
    for raw in (text or "").splitlines():
        m=ROW_RE.match(raw)
        if not m:continue
        cusip="".join(m.group(i) for i in (1,2,3)).upper()
        if not valid_cusip(cusip):continue
        rest=m.group(4).strip()
        # Historical SEC PDF text uses a fixed issuer-name field visually; text
        # extraction preserves the row order but not exact columns. Preserve the
        # full tail for audit and use a conservative first 30 chars as issuer field.
        issuer=rest[:30].strip()
        if not normalize_entity_name(issuer):continue
        rows.append({"cusip":cusip,"issuer_name":issuer,"row_text":rest})
    return pd.DataFrame(rows).drop_duplicates()

def summary(frame:pd.DataFrame)->dict:
    return {"rows":int(len(frame)),"unique_cusips":int(frame["cusip"].nunique()) if len(frame) else 0,
            "unique_issuer_names":int(frame["issuer_name"].nunique()) if len(frame) else 0}
