from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.sec_fsds_names import build_filing_names,normalize_cik
from finrisk.identity.resolution import normalize_entity_name

def hardcase_frame(identity:pd.DataFrame,limit:int=100)->pd.DataFrame:
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    return hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(limit)

def incremental_identity_report(identity:pd.DataFrame,filing_names:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    rows=[]
    for _,r in identity.iterrows():
        first=pd.Timestamp(r["first_filing"]);last=pd.Timestamp(r["last_filing"])
        eligible=last>=pd.Timestamp("2009-01-01")
        cik=normalize_cik(r["cik"])\n        observed=filing_names[filing_names["cik"].map(normalize_cik).eq(cik)] if len(filing_names) else pd.DataFrame()
        frozen=set(normalize_entity_name(x) for x in (r["historical_names"] if isinstance(r["historical_names"],list) else []))
        fsds=set(normalize_entity_name(x) for x in observed.get("name",pd.Series(dtype=str)).dropna())
        new=sorted(x for x in fsds if x and x not in frozen)
        rows.append({"cik":r["cik"],"first_filing":first,"last_filing":last,"fsds_eligible":eligible,
                     "fsds_observed":bool(len(observed)),"fsds_name_count":len(fsds),
                     "incremental_name_count":len(new),"incremental_names":new,
                     "status":"out_of_scope" if not eligible else ("observed" if len(observed) else "eligible_missing")})
    d=pd.DataFrame(rows);eligible=d[d["fsds_eligible"]]
    report={"hard_cases":len(d),"eligible":len(eligible),"out_of_scope":int((~d["fsds_eligible"]).sum()),
            "eligible_observed":int(eligible["fsds_observed"].sum()),
            "eligible_missing":int((~eligible["fsds_observed"]).sum()),
            "eligible_coverage":float(eligible["fsds_observed"].mean()) if len(eligible) else None,
            "with_incremental_names":int((eligible["incremental_name_count"]>0).sum()),
            "incremental_name_rate":float((eligible["incremental_name_count"]>0).mean()) if len(eligible) else None}
    return d,report

def build_hardcase_filing_names(identity_path:Path,out_dir:Path,user_agent:str,limit:int=100)->dict:
    identity=pd.read_parquet(identity_path);hard=hardcase_frame(identity,limit)
    build_filing_names(set(hard["cik"].astype(str)),2009,2026,out_dir,user_agent)
    names=pd.read_parquet(out_dir/"sec_filing_names.parquet")
    detail,report=incremental_identity_report(hard,names)
    detail.to_parquet(out_dir/"hardcase_incremental_identity.parquet",index=False)
    (out_dir/"hardcase_incremental_identity.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
