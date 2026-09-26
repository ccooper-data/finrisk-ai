from __future__ import annotations
import json
from pathlib import Path

ALLOWED_STATUS={"exploratory","candidate","promoted","rejected"}

def experiment_record(experiment_id:str,model:str,status:str,code_sha:str,data_artifacts:dict,
                      metrics:dict,decision:str,limitations:list[str]|None=None)->dict:
    if status not in ALLOWED_STATUS:raise ValueError(f"invalid status: {status}")
    if status=="promoted" and not decision.strip():raise ValueError("promoted experiment requires decision rationale")
    return {"experiment_id":experiment_id,"model":model,"status":status,"code_sha":code_sha,
            "data_artifacts":data_artifacts,"metrics":metrics,"decision":decision,"limitations":limitations or []}

def append_registry(path:Path,record:dict):
    records=[]
    if path.exists():records=json.loads(path.read_text())
    if any(r["experiment_id"]==record["experiment_id"] for r in records):raise ValueError("duplicate experiment_id")
    records.append(record);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(records,indent=2,sort_keys=True))
