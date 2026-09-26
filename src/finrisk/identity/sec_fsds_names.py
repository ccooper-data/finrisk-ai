from __future__ import annotations
import io,zipfile,hashlib,json
from pathlib import Path
import httpx,pandas as pd

def quarter_url(year:int,quarter:int)->str:
    return f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{year}q{quarter}.zip"

def fetch_sub(year:int,quarter:int,user_agent:str)->tuple[pd.DataFrame,dict]:
    url=quarter_url(year,quarter)
    r=httpx.get(url,headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"},timeout=180)
    if r.status_code==404:
        return pd.DataFrame(),{"year":year,"quarter":quarter,"source":url,"status":"source_not_published",
                              "http_status":404,"sha256":None,"bytes":0,"rows":0}
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names={n.lower():n for n in z.namelist()}
        member=names.get("sub.txt") or names.get("sub.tsv")
        if not member:raise ValueError(f"SUB file missing from {url}")
        df=pd.read_csv(z.open(member),sep="\t",dtype={"cik":str,"adsh":str},low_memory=False)
    keep=[c for c in ["adsh","cik","name","filed","form","period"] if c in df.columns]
    df=df[keep].copy();df["cik"]=df["cik"].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(10)
    if "filed" in df:df["filed"]=pd.to_datetime(df["filed"].astype(str),format="%Y%m%d",errors="coerce")
    evidence={"year":year,"quarter":quarter,"source":url,"sha256":hashlib.sha256(r.content).hexdigest(),
              "bytes":len(r.content),"rows":len(df)}
    return df,evidence

def build_filing_names(ciks:set[str],start_year:int,end_year:int,out_dir:Path,user_agent:str)->dict:
    wanted={str(x).zfill(10) for x in ciks};parts=[];sources=[]
    for year in range(start_year,end_year+1):
        for q in range(1,5):
            df,e=fetch_sub(year,q,user_agent);sources.append(e)
            hit=df[df["cik"].isin(wanted)]
            if len(hit):parts.append(hit)
    out=pd.concat(parts,ignore_index=True).drop_duplicates() if parts else pd.DataFrame()
    out_dir.mkdir(parents=True,exist_ok=True);out.to_parquet(out_dir/"sec_filing_names.parquet",index=False)
    manifest={"start_year":start_year,"end_year":end_year,"requested_ciks":len(wanted),
              "matched_ciks":int(out["cik"].nunique()) if len(out) else 0,"rows":len(out),
              "retrieved_quarters":sum(s.get("status")=="retrieved" for s in sources),
              "unpublished_quarters":[{"year":s["year"],"quarter":s["quarter"],"http_status":s["http_status"]}
                                      for s in sources if s.get("status")=="source_not_published"],
              "sources":sources}
    (out_dir/"sec_filing_names_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True,default=str))
    return manifest
