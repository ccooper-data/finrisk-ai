from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.candidate_discovery import discover_candidates
from finrisk.identity.resolution import normalize_entity_name
from finrisk.identity.sec_fsds_names import normalize_cik

def alias_map(filing_names:pd.DataFrame)->dict[str,list[str]]:
    out={}
    for cik,g in filing_names.groupby(filing_names["cik"].map(normalize_cik)):
        vals=sorted({str(x) for x in g["name"].dropna() if normalize_entity_name(str(x))})
        out[str(cik)]=vals
    return out

def compare_discovery(identity:pd.DataFrame,filing_names:pd.DataFrame,universe:pd.DataFrame,
                      min_score:float=.45,limit:int=100)->tuple[pd.DataFrame,dict]:
    amap=alias_map(filing_names);rows=[]
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    hard=hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(limit)
    for _,r in hard.iterrows():
        cik=normalize_cik(r["cik"]);base=r["historical_names"] if isinstance(r["historical_names"],list) else []
        enriched=sorted(set(base+amap.get(cik,[])))
        before=discover_candidates(cik,base,universe,min_score=min_score,limit=5)
        after=discover_candidates(cik,enriched,universe,min_score=min_score,limit=5)
        b=float(before.iloc[0]["discovery_score"]) if len(before) else None
        a=float(after.iloc[0]["discovery_score"]) if len(after) else None
        rows.append({"cik":cik,"base_aliases":len(base),"enriched_aliases":len(enriched),
                     "before_candidates":len(before),"after_candidates":len(after),
                     "before_top_score":b,"after_top_score":a,
                     "new_candidate":len(before)==0 and len(after)>0,
                     "candidate_count_increased":len(after)>len(before),
                     "top_score_improved":a is not None and (b is None or a>b)})
    d=pd.DataFrame(rows)
    report={"issuers":len(d),"before_with_candidate":int((d["before_candidates"]>0).sum()),
            "after_with_candidate":int((d["after_candidates"]>0).sum()),
            "new_candidate_issuers":int(d["new_candidate"].sum()),
            "candidate_count_increased":int(d["candidate_count_increased"].sum()),
            "top_score_improved":int(d["top_score_improved"].sum()),
            "min_discovery_score":min_score}
    return d,report

def write_impact(out_dir:Path,detail:pd.DataFrame,report:dict):
    out_dir.mkdir(parents=True,exist_ok=True);detail.to_parquet(out_dir/"fsds_discovery_impact.parquet",index=False)
    (out_dir/"fsds_discovery_impact.json").write_text(json.dumps(report,indent=2,sort_keys=True))
