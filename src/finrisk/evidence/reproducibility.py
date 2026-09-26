from __future__ import annotations
import json,platform,sys
from pathlib import Path
import importlib.metadata as md

def environment_manifest(code_sha:str,artifacts:dict[str,str],seed:int|None=None)->dict:
    packages={}
    for name in ["numpy","pandas","scikit-learn","pyarrow","torch","tensorflow"]:
        try:packages[name]=md.version(name)
        except md.PackageNotFoundError:pass
    return {"code_sha":code_sha,"python":sys.version.split()[0],"platform":platform.platform(),
            "packages":packages,"artifacts":artifacts,"seed":seed}

def write_environment_manifest(path:Path,manifest:dict):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(manifest,indent=2,sort_keys=True))
