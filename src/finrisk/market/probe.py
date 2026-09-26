from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def summarize_provider_probe(sample:pd.DataFrame,candidates:pd.DataFrame,prices:pd.DataFrame)->dict:
    s=sample.copy();c=candidates.copy();p=prices.copy()
    resolved=set(c.loc[c["decision"].eq("accepted_identifier"),"cik"].astype(str))
    priced=set(p["security_id"].astype(str)) if "security_id" in p else set()
    accepted=c[c["decision"].eq("accepted_identifier")]
    accepted_priced=set(accepted.loc[accepted["security_id"].astype(str).isin(priced),"cik"].astype(str))
    out={"sample_companies":int(s["cik"].nunique()),"resolved_companies":len(resolved),
         "resolved_rate":len(resolved)/max(1,int(s["cik"].nunique())),
         "priced_companies":len(accepted_priced),"priced_rate":len(accepted_priced)/max(1,int(s["cik"].nunique())),
         "by_group":{}}
    for group,g in s.groupby("probe_group"):
        ids=set(g["cik"].astype(str));out["by_group"][str(group)]={"companies":len(ids),
          "resolved":len(ids&resolved),"priced":len(ids&accepted_priced)}
    return out

def write_probe_report(path:Path,report:dict):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2,sort_keys=True))
