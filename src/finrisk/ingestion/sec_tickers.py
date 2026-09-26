from __future__ import annotations
import hashlib,json
from pathlib import Path
import httpx,pandas as pd

SEC_TICKERS="https://www.sec.gov/files/company_tickers.json"

def fetch_sec_ticker_map(user_agent:str)->tuple[pd.DataFrame,dict]:
    r=httpx.get(SEC_TICKERS,headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"},timeout=60)
    r.raise_for_status();raw=r.content;payload=r.json()
    rows=[]
    for item in payload.values():
        rows.append({"cik":str(item["cik_str"]).zfill(10),"ticker":str(item["ticker"]).upper(),"title":item["title"]})
    df=pd.DataFrame(rows).drop_duplicates(["cik","ticker"]).sort_values(["cik","ticker"])
    evidence={"source":SEC_TICKERS,"rows":len(df),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
    return df,evidence

def build_sec_ticker_map(out_dir:Path,user_agent:str)->dict:
    df,evidence=fetch_sec_ticker_map(user_agent);out_dir.mkdir(parents=True,exist_ok=True)
    df.to_parquet(out_dir/"sec_ticker_map.parquet",index=False)
    (out_dir/"sec_ticker_manifest.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    return evidence
