from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.candidate_discovery import discover_candidates

def discovery_diagnostic(identity:pd.DataFrame,universe:pd.DataFrame,n_issuers:int=100,min_score:float=.45)->tuple[pd.DataFrame,dict]:
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    rows=[];summary={"issuers_examined":0,"with_candidates":0,"without_candidates":0,"score_bands":{}}
    for _,r in hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(n_issuers).iterrows():
        aliases=r["historical_names"] if isinstance(r["historical_names"],list) else []
        c=discover_candidates(r["cik"],aliases,universe,min_score=min_score,limit=5)
        summary["issuers_examined"]+=1
        if c.empty:
            summary["without_candidates"]+=1
            rows.append({"cik":r["cik"],"rank":None,"security_id":None,"security_name":None,"score":None,"margin":None})
            continue
        summary["with_candidates"]+=1;c=c.reset_index(drop=True)
        top=float(c.loc[0,"discovery_score"]);second=float(c.loc[1,"discovery_score"]) if len(c)>1 else 0.
        for i,x in c.iterrows():
            rows.append({"cik":r["cik"],"rank":i+1,"security_id":x["security_id"],"security_name":x["security_name"],
                         "score":float(x["discovery_score"]),"margin":top-second if i==0 else None,
                         "sec_alias":x["sec_alias"],"is_delisted":x.get("is_delisted")})
    detail=pd.DataFrame(rows)
    tops=detail[detail["rank"].eq(1)]["score"].dropna()
    for lo,hi in [(0,.5),(.5,.6),(.6,.7),(.7,.8),(.8,.9),(.9,1.01)]:
        summary["score_bands"][f"{lo:.1f}-{min(hi,1):.1f}"]=int(((tops>=lo)&(tops<hi)).sum())
    summary["top_score_median"]=float(tops.median()) if len(tops) else None
    summary["top_score_max"]=float(tops.max()) if len(tops) else None
    margins=detail[detail["rank"].eq(1)]["margin"].dropna()
    summary["margin_median"]=float(margins.median()) if len(margins) else None
    return detail,summary

def write_diagnostic(out_dir:Path,detail:pd.DataFrame,summary:dict):
    out_dir.mkdir(parents=True,exist_ok=True);detail.to_parquet(out_dir/"candidate_discovery_detail.parquet",index=False)
    (out_dir/"candidate_discovery_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
