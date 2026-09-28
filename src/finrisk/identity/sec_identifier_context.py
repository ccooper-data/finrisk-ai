from __future__ import annotations
import re,pandas as pd

SECURITY_TERMS=("common stock","common shares","ordinary shares","class a","class b","equity security")
DEBT_TERMS=("note","notes","debenture","bond","senior secured","senior unsecured","convertible note")
PREFERRED_TERMS=("preferred stock","preferred shares","preference shares")

def identifier_match(text:str,identifier:str):
    return re.search(re.escape(identifier),text or "",re.I)

def context_window(text:str,identifier:str,radius:int=220)->str:
    s=text or "";m=identifier_match(s,identifier)
    if not m:return ""
    return s[max(0,m.start()-radius):min(len(s),m.end()+radius)]

def classify_identifier_context(window:str)->dict:
    w=(window or "").lower()
    equity=any(x in w for x in SECURITY_TERMS)
    debt=any(x in w for x in DEBT_TERMS)
    preferred=any(x in w for x in PREFERRED_TERMS)
    if equity and not debt and not preferred:kind="common_equity"
    elif debt and not equity:kind="debt"
    elif preferred:kind="preferred"
    elif equity or debt:kind="ambiguous_security_type"
    else:kind="unknown"
    return {"security_context":kind,"common_equity_context":kind=="common_equity"}

def contextualize_identifiers(text:str,identifiers:list[str])->pd.DataFrame:
    rows=[];s=text or ""
    for value in identifiers:
        m=identifier_match(s,value);window=context_window(s,value);c=classify_identifier_context(window)
        rows.append({"identifier":value,"match_start":m.start() if m else None,"match_end":m.end() if m else None,
                     "context":window,**c})
    return pd.DataFrame(rows)
