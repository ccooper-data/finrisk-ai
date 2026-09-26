from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def model_evidence(model_name:str,framework:str,data_artifacts:dict[str,str],split:dict[str,str],
                   features:list[str],metrics:dict[str,Any],code_sha:str,limitations:list[str]|None=None)->dict:
    return {"schema_version":"2.0","model":model_name,"framework":framework,"code_sha":code_sha,
            "data_artifacts":data_artifacts,"temporal_split":split,"features":features,"metrics":metrics,
            "limitations":limitations or []}

def validate_model_evidence(e:dict)->None:
    required={"schema_version","model","framework","code_sha","data_artifacts","temporal_split","features","metrics","limitations"}
    missing=required-set(e)
    if missing:raise ValueError(f"Missing model evidence fields: {sorted(missing)}")
    if not e["data_artifacts"]:raise ValueError("At least one frozen data artifact is required")
    if "test" not in e["metrics"]:raise ValueError("Out-of-time test metrics are required")
