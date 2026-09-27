from __future__ import annotations
import hashlib,time
import httpx

def accession_base_url(cik:str,accession:str)->str:
    c=str(int(str(cik).replace(".0","")))
    a=str(accession).replace("-","")
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{a}"

def fetch_accession_index(cik:str,accession:str,user_agent:str,client:httpx.Client|None=None)->tuple[dict,dict]:
    base=accession_base_url(cik,accession);url=f"{base}/index.json";own=client is None
    client=client or httpx.Client(headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"},timeout=60)
    try:
        r=client.get(url);r.raise_for_status();payload=r.json()
        evidence={"cik":str(cik),"accession":accession,"url":url,"http_status":r.status_code,
                  "sha256":hashlib.sha256(r.content).hexdigest(),"bytes":len(r.content)}
        return payload,evidence
    finally:
        if own:client.close()

def accession_documents(index_payload:dict,base_url:str)->list[dict]:
    items=index_payload.get("directory",{}).get("item",[]) or [];rows=[]
    for x in items:
        name=x.get("name","")
        if not name or name.endswith("/"):continue
        rows.append({"name":name,"size":x.get("size"),"url":f"{base_url}/{name}"})
    return rows
