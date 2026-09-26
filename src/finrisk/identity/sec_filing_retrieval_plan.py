from __future__ import annotations
import pandas as pd

PRIORITY_FORMS=("10-K","10-K/A","10-Q","10-Q/A","8-K","8-K/A")

def filing_retrieval_plan(targets:pd.DataFrame,filing_names:pd.DataFrame,max_filings_per_cik:int=6)->pd.DataFrame:
    rows=[]
    for _,t in targets.iterrows():
        cik=str(t["cik"])
        f=filing_names[filing_names["cik"].astype(str).eq(cik)].copy()
        if f.empty:continue
        f=f[f["form"].isin(PRIORITY_FORMS)] if "form" in f else f
        f=f.sort_values("filed",ascending=False).drop_duplicates("adsh").head(max_filings_per_cik)
        for _,x in f.iterrows():
            rows.append({"cik":cik,"candidate_security_id":t["top_security_id"],
                         "target_priority":t["target_priority"],"accession":x["adsh"],
                         "filing_date":str(pd.Timestamp(x["filed"]).date()),"form":x.get("form"),
                         "retrieval_status":"planned"})
    return pd.DataFrame(rows)

def retrieval_summary(plan:pd.DataFrame)->dict:
    return {"targets_with_filings":int(plan["cik"].nunique()) if len(plan) else 0,
            "planned_filings":len(plan),"max_filings_per_target":int(plan.groupby("cik").size().max()) if len(plan) else 0}
