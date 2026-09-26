from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def validate_fred_context(path:Path,out_path:Path)->dict:
    df=pd.read_parquet(path);df["date"]=pd.to_datetime(df["date"])
    features=[c for c in df.columns if c!="date"]
    report={"rows":int(len(df)),"start":str(df["date"].min().date()),"end":str(df["date"].max().date()),
            "duplicate_dates":int(df["date"].duplicated().sum()),"features":{}}
    for c in features:
        s=df[c]
        report["features"][c]={"non_null":int(s.notna().sum()),"coverage":float(s.notna().mean()),
                               "first_available":str(df.loc[s.notna(),"date"].min().date()) if s.notna().any() else None,
                               "last_available":str(df.loc[s.notna(),"date"].max().date()) if s.notna().any() else None,
                               "min":float(s.min()) if s.notna().any() else None,"max":float(s.max()) if s.notna().any() else None}
    if report["duplicate_dates"]:raise ValueError("FRED context contains duplicate dates")
    out_path.parent.mkdir(parents=True,exist_ok=True);out_path.write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
