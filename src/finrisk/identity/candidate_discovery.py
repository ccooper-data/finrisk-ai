from __future__ import annotations
from difflib import SequenceMatcher
import pandas as pd
from finrisk.identity.resolution import normalize_entity_name

def token_jaccard(a:str,b:str)->float:
    x,y=set(normalize_entity_name(a).split()),set(normalize_entity_name(b).split())
    return len(x&y)/len(x|y) if x and y else 0.0

def name_similarity(a:str,b:str)->float:
    na,nb=normalize_entity_name(a),normalize_entity_name(b)
    if not na or not nb:return 0.0
    return max(token_jaccard(a,b),SequenceMatcher(None,na,nb).ratio())

def discover_candidates(cik:str,aliases:list[str],universe:pd.DataFrame,min_score:float=.72,limit:int=10)->pd.DataFrame:
    rows=[]
    for _,s in universe.iterrows():
        best_alias=None;best=0.0
        for alias in aliases:
            score=name_similarity(alias,str(s["security_name"]))
            if score>best:best,best_alias=score,alias
        if best>=min_score:
            rows.append({"cik":str(cik),"sec_alias":best_alias,"security_id":s["security_id"],
                         "security_name":s["security_name"],"discovery_score":best,
                         "isin":s.get("isin"),"is_delisted":s.get("is_delisted"),
                         "discovery_only":True})
    if not rows:return pd.DataFrame(columns=["cik","sec_alias","security_id","security_name","discovery_score","isin","is_delisted","discovery_only"])
    return pd.DataFrame(rows).sort_values(["discovery_score","is_delisted"],ascending=[False,False]).head(limit).reset_index(drop=True)

def discovery_for_hard_cases(identity:pd.DataFrame,universe:pd.DataFrame,n_issuers:int=10)->pd.DataFrame:
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    out=[]
    for _,r in hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).iterrows():
        aliases=r["historical_names"] if isinstance(r["historical_names"],list) else []
        c=discover_candidates(r["cik"],aliases,universe)
        if len(c):
            c["first_filing"]=r["first_filing"];c["last_filing"]=r["last_filing"];out.append(c)
        if len(out)>=n_issuers:break
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame()
