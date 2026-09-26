from __future__ import annotations
import pandas as pd

REQUIRED_DELISTING={"security_id","delist_date","delist_code","delist_return","source","source_identifier"}

def validate_delistings(df:pd.DataFrame)->None:
    missing=REQUIRED_DELISTING-set(df.columns)
    if missing:raise ValueError(f"Missing delisting fields: {sorted(missing)}")
    if df.duplicated(["security_id","delist_date"]).any():raise ValueError("Duplicate security/delist-date rows")

def apply_delisting_returns(prices:pd.DataFrame,delistings:pd.DataFrame)->pd.DataFrame:
    validate_delistings(delistings);p=prices.copy()\n    if "date" in p.columns:p["date"]=pd.to_datetime(p["date"])
    d=delistings.copy();d["delist_date"]=pd.to_datetime(d["delist_date"])
    rows=[]
    for _,r in d.iterrows():
        if pd.isna(r["delist_return"]):continue
        rows.append({"security_id":r["security_id"],"date":r["delist_date"],"delist_return":float(r["delist_return"]),
                     "is_delisting_observation":True,"source":r["source"],"source_identifier":r["source_identifier"]})
    events=pd.DataFrame(rows)
    return events
