from __future__ import annotations
import pandas as pd

def add_relative_market_features(security:pd.DataFrame,benchmark:pd.DataFrame)->pd.DataFrame:
    s=security.copy();b=benchmark.copy();s["date"]=pd.to_datetime(s["date"]);b["date"]=pd.to_datetime(b["date"])
    b=b.sort_values("date");s=s.sort_values(["security_id","date"])
    for n in [21,63,252]:
        b[f"benchmark_ret_{n}d"]=b["close"].pct_change(n,fill_method=None)
    out=s.merge(b[["date","benchmark_ret_21d","benchmark_ret_63d","benchmark_ret_252d"]],on="date",how="left")
    for n in [21,63,252]:
        sec=out.groupby("security_id")["close"].pct_change(n,fill_method=None)
        out[f"excess_ret_{n}d"]=sec-out[f"benchmark_ret_{n}d"]
    return out
