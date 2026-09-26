from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.resolution import build_identity_master

def audit_historical_identity(cohort_path:Path,ticker_path:Path,names_path:Path,out_dir:Path)->dict:
    c=pd.read_parquet(cohort_path);t=pd.read_parquet(ticker_path);h=pd.read_parquet(names_path)
    master=build_identity_master(c,t,h)
    distressed=master[master["distress_observations"]>0]
    missing_current=distressed[~distressed["has_current_ticker"]]
    report={"cohort_companies":int(len(master)),"historical_name_coverage":float(master["has_historical_name"].mean()),
      "current_ticker_coverage":float(master["has_current_ticker"].mean()),
      "distressed_companies":int(len(distressed)),"distressed_without_current_ticker":int(len(missing_current)),
      "distressed_without_current_ticker_with_historical_names":int(missing_current["has_historical_name"].sum()),
      "distressed_name_recovery_rate":float(missing_current["has_historical_name"].mean()) if len(missing_current) else 1.0,
      "unresolved_companies":int((master["identity_status"]=="unresolved").sum())}
    out_dir.mkdir(parents=True,exist_ok=True);master.to_parquet(out_dir/"historical_identity_master.parquet",index=False)
    (out_dir/"historical_identity_audit.json").write_text(json.dumps(report,indent=2,sort_keys=True));return report
