from __future__ import annotations
import pandas as pd
import numpy as np

MARKET_FEATURES=["ret_21d","ret_63d","ret_252d","vol_63d","drawdown_252d","distance_52w_high","volume_z_63d"]
MACRO_FEATURES=["treasury_3m","treasury_10y","yield_curve_10y_3m","unemployment","cpi_yoy","industrial_production_yoy","credit_spread"]

def market_features(prices:pd.DataFrame)->pd.DataFrame:
    p=prices.copy();p["date"]=pd.to_datetime(p["date"]);p=p.sort_values(["cik","date"])
    g=p.groupby("cik",sort=False)
    p["ret_21d"]=g["close"].pct_change(21,fill_method=None)
    p["ret_63d"]=g["close"].pct_change(63,fill_method=None)
    p["ret_252d"]=g["close"].pct_change(252,fill_method=None)
    daily=g["close"].pct_change(fill_method=None)
    p["vol_63d"]=daily.groupby(p["cik"]).rolling(63,min_periods=20).std().reset_index(level=0,drop=True)*np.sqrt(252)
    high=g["close"].rolling(252,min_periods=20).max().reset_index(level=0,drop=True)
    p["drawdown_252d"]=p["close"]/high-1
    p["distance_52w_high"]=p["close"]/high-1
    vol_mean=g["volume"].rolling(63,min_periods=20).mean().reset_index(level=0,drop=True)
    vol_std=g["volume"].rolling(63,min_periods=20).std().reset_index(level=0,drop=True)
    p["volume_z_63d"]=(p["volume"]-vol_mean)/vol_std
    return p

def macro_features(macro:pd.DataFrame)->pd.DataFrame:
    m=macro.copy();m["date"]=pd.to_datetime(m["date"]);m=m.sort_values("date")
    if {"treasury_10y","treasury_3m"}.issubset(m):m["yield_curve_10y_3m"]=m["treasury_10y"]-m["treasury_3m"]
    if "cpi" in m:m["cpi_yoy"]=m["cpi"].pct_change(12,fill_method=None)
    if "industrial_production" in m:m["industrial_production_yoy"]=m["industrial_production"].pct_change(12,fill_method=None)
    return m

def point_in_time_join(filings:pd.DataFrame,prices:pd.DataFrame|None=None,macro:pd.DataFrame|None=None)->pd.DataFrame:
    out=filings.copy();out["filed"]=pd.to_datetime(out["filed"]);out["_order"]=np.arange(len(out))
    if prices is not None:
        mf=market_features(prices)
        parts=[]
        for cik,g in out.groupby("cik",sort=False):
            hist=mf[mf["cik"].astype(str).eq(str(cik))].sort_values("date")
            if hist.empty:parts.append(g);continue
            parts.append(pd.merge_asof(g.sort_values("filed"),hist[["date"]+[c for c in MARKET_FEATURES if c in hist]],
                                       left_on="filed",right_on="date",direction="backward",allow_exact_matches=True))
        out=pd.concat(parts,ignore_index=True)
    if macro is not None:
        mm=macro_features(macro);cols=["date"]+[c for c in MACRO_FEATURES if c in mm]
        out=pd.merge_asof(out.sort_values("filed"),mm[cols].sort_values("date"),left_on="filed",right_on="date",
                          direction="backward",allow_exact_matches=True,suffixes=("","_macro"))
    return out.sort_values("_order").drop(columns=["_order"],errors="ignore").reset_index(drop=True)
