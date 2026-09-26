from __future__ import annotations
import hashlib,json
from pathlib import Path
import httpx,pandas as pd

FRED_CSV="https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES={
 "treasury_3m":"DGS3MO","treasury_10y":"DGS10","unemployment":"UNRATE",
 "cpi":"CPIAUCSL","industrial_production":"INDPRO","credit_spread":"BAA10Y",
}

def fetch_fred_series(series_id:str,start:str="2008-01-01")->tuple[pd.DataFrame,bytes]:
    params={"id":series_id,"cosd":start}
    r=httpx.get(FRED_CSV,params=params,timeout=120);r.raise_for_status();raw=r.content
    from io import BytesIO
    df=pd.read_csv(BytesIO(raw));df.columns=["date","value"];df["date"]=pd.to_datetime(df["date"])
    df["value"]=pd.to_numeric(df["value"],errors="coerce")
    return df.dropna(subset=["value"]),raw

def build_macro_context(out_dir:Path,start:str="2008-01-01")->dict:
    out_dir.mkdir(parents=True,exist_ok=True);frames=[];sources=[]
    for name,sid in SERIES.items():
        df,raw=fetch_fred_series(sid,start);df=df.rename(columns={"value":name});frames.append(df)
        sources.append({"feature":name,"series_id":sid,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)})
    # Daily union followed by backward fill from each series' latest published observation.
    all_dates=pd.DataFrame({"date":sorted(set().union(*(set(f["date"]) for f in frames)))})
    merged=all_dates
    for f in frames:merged=merged.merge(f,on="date",how="left")
    merged=merged.sort_values("date").ffill()
    merged.to_parquet(out_dir/"fred_macro.parquet",index=False)
    manifest={"provider":"Federal Reserve Bank of St. Louis FRED","start":start,"rows":len(merged),"sources":sources}
    (out_dir/"fred_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True))
    return manifest
