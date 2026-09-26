from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.sec_fsds_names import build_filing_names

def hardcase_ciks(identity:pd.DataFrame,limit:int=100)->list[str]:
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    return hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(limit)["cik"].astype(str).tolist()

def build_hardcase_filing_names(identity_path:Path,out_dir:Path,user_agent:str,limit:int=100)->dict:
    identity=pd.read_parquet(identity_path);ciks=hardcase_ciks(identity,limit)
    m=build_filing_names(set(ciks),2009,2026,out_dir,user_agent)
    rate=m["matched_ciks"]/max(1,len(ciks))
    report={"hardcase_ciks":len(ciks),"matched_ciks":m["matched_ciks"],"hit_rate":rate,
            "filing_name_rows":m["rows"],"source":"SEC Financial Statement Data Sets SUB"}
    (out_dir/"hardcase_hit_rate.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
