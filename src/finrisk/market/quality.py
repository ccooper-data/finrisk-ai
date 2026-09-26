from __future__ import annotations
import pandas as pd

def validate_price_history(df:pd.DataFrame,max_gap_days:int=14)->dict:
    required={"security_id","date","close","volume","source","retrieved_at"}
    missing=required-set(df.columns)
    if missing:raise ValueError(f"Missing price fields: {sorted(missing)}")
    x=df.copy();x["date"]=pd.to_datetime(x["date"])
    if x.duplicated(["security_id","date"]).any():raise ValueError("Duplicate security/date prices")
    if (x["close"]<=0).any():raise ValueError("Non-positive close price")
    if (x["volume"]<0).any():raise ValueError("Negative volume")
    gaps={}
    for sid,g in x.sort_values("date").groupby("security_id"):
        d=g["date"].diff().dt.days.dropna()
        gaps[str(sid)]={"max_calendar_gap_days":int(d.max()) if len(d) else 0,
                        "gaps_over_threshold":int((d>max_gap_days).sum())}
    return {"rows":int(len(x)),"securities":int(x["security_id"].nunique()),"gaps":gaps}
