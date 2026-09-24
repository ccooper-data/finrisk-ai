from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json, platform, sys
from pathlib import Path
import pandas as pd
from finrisk.cohort_builder import CohortBuildConfig, build_labeled_sec_cohort, cohort_inventory, quarters

def file_sha256(path:Path,chunk_size:int=1024*1024)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk=f.read(chunk_size)
            if not chunk:break
            h.update(chunk)
    return h.hexdigest()

def source_manifest(cache_dir:Path)->list[dict]:
    return [{"path":str(p.relative_to(cache_dir)),"bytes":p.stat().st_size,"sha256":file_sha256(p)}
            for p in sorted(cache_dir.rglob("*.zip"))]

def quarter_inventory(cache_dir:Path,config:CohortBuildConfig)->pd.DataFrame:
    rows=[]
    for q in quarters(config):
        p=cache_dir/"fsds"/f"{q.slug}.zip"
        rows.append({"quarter":q.slug,"url":q.url,"cached":p.exists() and p.stat().st_size>0,
                     "bytes":p.stat().st_size if p.exists() else 0,
                     "sha256":file_sha256(p) if p.exists() and p.stat().st_size>0 else None})
    return pd.DataFrame(rows)

def write_run_evidence(out_dir,config,cohort,events,cache_dir):
    out_dir.mkdir(parents=True,exist_ok=True)
    qinv=quarter_inventory(cache_dir,config);qinv.to_csv(out_dir/"quarter_inventory.csv",index=False)
    cohort.to_parquet(out_dir/"sec_labeled_cohort.parquet",index=False)
    events.to_parquet(out_dir/"distress_events.parquet",index=False)
    manifest={"artifact_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),"status":"complete",
              "config":asdict(config),"inventory":cohort_inventory(cohort,events),"sources":source_manifest(cache_dir),
              "runtime":{"python":sys.version,"platform":platform.platform()}}
    (out_dir/"run_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True,default=str))
    return manifest

def execute_real_sec_build(user_agent:str,cache_dir:Path,out_dir:Path,config:CohortBuildConfig|None=None)->dict:
    config=config or CohortBuildConfig();out_dir.mkdir(parents=True,exist_ok=True)
    try:
        cohort,events=build_labeled_sec_cohort(config,user_agent,cache_dir)
        return write_run_evidence(out_dir,config,cohort,events,cache_dir)
    except Exception as exc:
        failure={"artifact_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),"status":"failed",
                 "config":asdict(config),"error_type":type(exc).__name__,"error":str(exc),"sources":source_manifest(cache_dir)}
        (out_dir/"run_manifest.json").write_text(json.dumps(failure,indent=2,sort_keys=True,default=str))
        raise
