from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd

def hash_file(path:Path)->dict:
    h=hashlib.sha256();size=0
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk);size+=len(chunk)
    return {"sha256":h.hexdigest(),"bytes":size}

def market_ingestion_manifest(provider:str,retrieved_at:str,security_master:Path,prices:Path,
                              delistings:Path|None=None,corporate_actions:Path|None=None,
                              benchmark:Path|None=None)->dict:
    files={"security_master":hash_file(security_master),"prices":hash_file(prices)}
    for name,path in [("delistings",delistings),("corporate_actions",corporate_actions),("benchmark",benchmark)]:
        if path is not None:files[name]=hash_file(path)
    return {"provider":provider,"retrieved_at":retrieved_at,"files":files,
            "scope":{"security_master":str(security_master),"prices":str(prices)}}

def write_market_manifest(path:Path,manifest:dict):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(manifest,indent=2,sort_keys=True))
