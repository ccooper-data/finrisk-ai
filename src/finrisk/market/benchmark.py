from __future__ import annotations
import pandas as pd

REQUIRED_BENCHMARK={"date","close","benchmark_id","source","retrieved_at"}

def validate_benchmark(df:pd.DataFrame)->dict:
    missing=REQUIRED_BENCHMARK-set(df.columns)
    if missing:raise ValueError(f"Missing benchmark fields: {sorted(missing)}")
    x=df.copy();x["date"]=pd.to_datetime(x["date"])
    if x["benchmark_id"].nunique()!=1:raise ValueError("One benchmark artifact must contain one benchmark identity")
    if x["date"].duplicated().any():raise ValueError("Duplicate benchmark dates")
    if (x["close"]<=0).any():raise ValueError("Non-positive benchmark close")
    return {"benchmark_id":str(x["benchmark_id"].iloc[0]),"rows":int(len(x)),
            "start":str(x["date"].min().date()),"end":str(x["date"].max().date())}
