from __future__ import annotations
import pandas as pd

def select_identifier_targets(candidate_strength:pd.DataFrame,max_targets:int=56)->pd.DataFrame:
    x=candidate_strength.copy()
    required={"cik","top_security_id","top_score","margin","isin_present","is_delisted"}
    missing=required-set(x.columns)
    if missing:raise ValueError(f"Missing fields: {sorted(missing)}")
    x=x[(x["isin_present"].eq(True))&(x["top_security_id"].notna())].copy()
    x["target_priority"]=x.apply(lambda r:
        "A_high_margin_isin" if r["top_score"]>=.90 and r["margin"]>=.08 else
        "B_strong_ambiguous_isin" if r["top_score"]>=.90 else
        "C_weak_isin",axis=1)
    order={"A_high_margin_isin":0,"B_strong_ambiguous_isin":1,"C_weak_isin":2}
    x["_order"]=x["target_priority"].map(order)
    return x.sort_values(["_order","top_score","margin"],ascending=[True,False,False]).drop(columns="_order").head(max_targets).reset_index(drop=True)

def target_summary(frame:pd.DataFrame)->dict:
    return {"targets":len(frame),"by_priority":{k:int(v) for k,v in frame["target_priority"].value_counts().to_dict().items()},
            "delisted_targets":int(frame["is_delisted"].eq(True).sum())}
