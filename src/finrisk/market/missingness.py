from __future__ import annotations
import pandas as pd

def add_market_missingness_indicators(frame:pd.DataFrame,market_features:list[str])->pd.DataFrame:
    out=frame.copy()
    present=[c for c in market_features if c in out]
    if not present:
        out["market_data_available"]=False
        return out
    out["market_data_available"]=out[present].notna().any(axis=1)
    for c in present:out[f"{c}__missing"]=out[c].isna().astype("int8")
    return out

def require_no_market_row_drop(before:pd.DataFrame,after:pd.DataFrame)->None:
    if len(before)!=len(after):raise ValueError(f"Market enrichment changed labeled population: {len(before)} -> {len(after)}")
