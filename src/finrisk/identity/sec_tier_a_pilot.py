from __future__ import annotations
import pandas as pd

def tier_a_pilot_plan(targets:pd.DataFrame,retrieval_plan:pd.DataFrame)->pd.DataFrame:
    tier=targets[targets["target_priority"].eq("A_high_margin_isin")][["cik","top_security_id"]].copy()
    if tier.empty:return retrieval_plan.iloc[0:0].copy()
    out=retrieval_plan.merge(tier,on=["cik","candidate_security_id"],how="inner")
    return out.sort_values(["cik","filing_date"],ascending=[True,False]).reset_index(drop=True)

def pilot_summary(plan:pd.DataFrame)->dict:
    return {"tier_a_targets":int(plan["cik"].nunique()) if len(plan) else 0,
            "planned_accessions":len(plan),
            "max_accessions_per_target":int(plan.groupby("cik").size().max()) if len(plan) else 0}
