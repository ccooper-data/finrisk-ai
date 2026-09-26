from __future__ import annotations
import hashlib,json
from pathlib import Path
import httpx,pandas as pd

SEC_CIK_NAMES="https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"

def build_historical_cik_names(out_dir:Path,user_agent:str)->dict:
    r=httpx.get(SEC_CIK_NAMES,headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"},timeout=120)
    r.raise_for_status();raw=r.content;rows=[]
    for line in r.text.splitlines():
        if not line.strip() or ":" not in line:continue
        name,cik=line.rsplit(":",1);cik=cik.strip()
        if not cik.isdigit():continue
        rows.append({"cik":cik.zfill(10),"historical_name":name.strip()})
    df=pd.DataFrame(rows).drop_duplicates().sort_values(["cik","historical_name"])
    out_dir.mkdir(parents=True,exist_ok=True);df.to_parquet(out_dir/"sec_historical_cik_names.parquet",index=False)
    evidence={"source":SEC_CIK_NAMES,"rows":len(df),"unique_ciks":int(df["cik"].nunique()),
              "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
              "scope":"SEC describes this CIK/name list as historically cumulative for company names; it is not a historical ticker map."}
    (out_dir/"sec_historical_names_manifest.json").write_text(json.dumps(evidence,indent=2,sort_keys=True));return evidence
