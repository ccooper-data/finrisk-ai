from __future__ import annotations
import numpy as np,pandas as pd

MARKET_V2=["ret_5d","ret_21d","ret_63d","ret_126d","ret_252d","vol_21d","vol_63d",
           "drawdown_63d","drawdown_252d","distance_52w_high","volume_z_21d","volume_z_63d",
           "downside_vol_63d","max_loss_63d"]

def engineer_market_history(prices:pd.DataFrame)->pd.DataFrame:
    p=prices.copy();p["date"]=pd.to_datetime(p["date"]);p=p.sort_values(["security_id","date"])
    g=p.groupby("security_id",sort=False);daily=g["close"].pct_change(fill_method=None)
    for n in [5,21,63,126,252]:p[f"ret_{n}d"]=g["close"].pct_change(n,fill_method=None)
    for n in [21,63]:
        p[f"vol_{n}d"]=daily.groupby(p["security_id"]).rolling(n,min_periods=max(10,n//3)).std().reset_index(level=0,drop=True)*np.sqrt(252)
        vm=g["volume"].rolling(n,min_periods=max(10,n//3)).mean().reset_index(level=0,drop=True)
        vs=g["volume"].rolling(n,min_periods=max(10,n//3)).std().reset_index(level=0,drop=True)
        p[f"volume_z_{n}d"]=(p["volume"]-vm)/vs
    for n in [63,252]:
        high=g["close"].rolling(n,min_periods=20).max().reset_index(level=0,drop=True)
        p[f"drawdown_{n}d"]=p["close"]/high-1
    high252=g["close"].rolling(252,min_periods=20).max().reset_index(level=0,drop=True)
    p["distance_52w_high"]=p["close"]/high252-1
    downside=daily.where(daily<0)
    p["downside_vol_63d"]=downside.groupby(p["security_id"]).rolling(63,min_periods=20).std().reset_index(level=0,drop=True)*np.sqrt(252)
    p["max_loss_63d"]=daily.groupby(p["security_id"]).rolling(63,min_periods=20).min().reset_index(level=0,drop=True)
    return p

def attach_market_asof(filings:pd.DataFrame,features:pd.DataFrame)->pd.DataFrame:
    f=filings.copy();f["filed"]=pd.to_datetime(f["filed"]);f["_order"]=np.arange(len(f))
    pieces=[]
    for sid,g in f.groupby("security_id",dropna=False,sort=False):
        if pd.isna(sid):pieces.append(g);continue
        hist=features[features["security_id"].eq(sid)].sort_values("date")
        if hist.empty:pieces.append(g);continue
        pieces.append(pd.merge_asof(g.sort_values("filed"),hist[["date"]+[c for c in MARKET_V2 if c in hist]],
                    left_on="filed",right_on="date",direction="backward",allow_exact_matches=True))
    return pd.concat(pieces,ignore_index=True).sort_values("_order").drop(columns=["_order"],errors="ignore")
