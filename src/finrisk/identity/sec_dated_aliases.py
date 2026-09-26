from __future__ import annotations
import hashlib,json
from pathlib import Path
import httpx,pandas as pd

def fetch_dated_aliases(ciks:list[str],user_agent:str)->tuple[pd.DataFrame,dict]:
    rows=[];sources=[]
    headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"}
    for cik in sorted(set(str(x).zfill(10) for x in ciks)):
        url=f"https://data.sec.gov/submissions/CIK{cik}.json"
        r=httpx.get(url,headers=headers,timeout=60);r.raise_for_status();payload=r.json()
        current=payload.get("name")
        if current:rows.append({"cik":cik,"name":current,"from_date":None,"to_date":None,"name_type":"current","source":url})
        for x in payload.get("formerNames",[]) or []:
            rows.append({"cik":cik,"name":x.get("name"),"from_date":x.get("from"),"to_date":x.get("to"),
                         "name_type":"former","source":url})
        sources.append({"cik":cik,"url":url,"sha256":hashlib.sha256(r.content).hexdigest(),"bytes":len(r.content)})
    return pd.DataFrame(rows).drop_duplicates(),{"ciks":len(sources),"sources":sources}

def build_dated_aliases(ciks:list[str],out_dir:Path,user_agent:str)->dict:
    df,evidence=fetch_dated_aliases(ciks,user_agent);out_dir.mkdir(parents=True,exist_ok=True)
    df.to_parquet(out_dir/"sec_dated_aliases.parquet",index=False)
    (out_dir/"sec_dated_aliases_manifest.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    return {"ciks":evidence["ciks"],"aliases":len(df),"former_aliases":int(df["name_type"].eq("former").sum())}
