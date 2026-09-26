from __future__ import annotations
import pandas as pd

def classify_security_evidence(candidates:pd.DataFrame)->pd.DataFrame:
    x=candidates.copy()
    required={"top_score","margin","isin_present","is_delisted","candidate_count"}
    missing=required-set(x.columns)
    if missing: raise ValueError(f"Missing candidate-strength fields: {sorted(missing)}")
    def tier(r):
        if r["top_score"]>=.90 and r["margin"]>=.08:
            return "A_high_margin"
        if r["top_score"]>=.90:
            return "B_strong_ambiguous"
        return "C_weak_needs_identifier"
    x["evidence_tier"]=x.apply(tier,axis=1)
    x["identifier_priority"]=x.apply(lambda r:
        "isin_corroboration" if bool(r["isin_present"]) else
        "cusip_or_historical_ticker_required",axis=1)
    x["price_probe_eligible"]=x["evidence_tier"].eq("A_high_margin")
    x["accepted_security"]=False
    return x

def tier_summary(frame:pd.DataFrame)->dict:
    counts=frame["evidence_tier"].value_counts().to_dict()
    return {"rows":len(frame),"tiers":{k:int(v) for k,v in counts.items()},
            "price_probe_eligible":int(frame["price_probe_eligible"].sum()),
            "accepted_security":int(frame["accepted_security"].sum())}
