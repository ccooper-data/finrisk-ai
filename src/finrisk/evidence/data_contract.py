from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd

def dataframe_contract(df:pd.DataFrame,required:list[str],unique:list[str]|None=None)->dict:
    missing=sorted(set(required)-set(df.columns))
    if missing:raise ValueError(f"Missing required columns: {missing}")
    dupes=int(df.duplicated(unique).sum()) if unique else 0
    if unique and dupes:raise ValueError(f"Duplicate key rows: {dupes}")
    return {"rows":int(len(df)),"columns":list(df.columns),"required":required,"unique_key":unique,
            "null_rates":{c:float(df[c].isna().mean()) for c in required},"duplicate_key_rows":dupes}

def write_contract(path:Path,contract:dict):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(contract,indent=2,sort_keys=True))
