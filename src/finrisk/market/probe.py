from __future__ import annotations
import pandas as pd

def evaluate_probe(probe:pd.DataFrame,resolutions:pd.DataFrame,prices:pd.DataFrame)->dict:
    p=probe.copy();r=resolutions.copy()
    merged=p.merge(r[["cik","security_id","security_resolution"]],on="cik",how="left")
    resolved=merged["security_resolution"].eq("accepted")
    priced=set(prices["security_id"].dropna().astype(str)) if "security_id" in prices else set()
    merged["has_prices"]=merged["security_id"].astype(str).isin(priced)&resolved
    out={}
    for group,g in merged.groupby("probe_group"):
        out[str(group)]={"companies":int(len(g)),"resolved":int(g["security_resolution"].eq("accepted").sum()),
                         "priced":int(g["has_prices"].sum()),"price_coverage":float(g["has_prices"].mean())}
    return {"groups":out,"overall_price_coverage":float(merged["has_prices"].mean())}
