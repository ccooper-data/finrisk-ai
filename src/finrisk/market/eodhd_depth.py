from __future__ import annotations
import pandas as pd
from finrisk.market.eodhd import EODHDProbeAdapter
from finrisk.identity.candidate_discovery import discovery_for_hard_cases

def choose_depth_probe(identity:pd.DataFrame,eod_universe:pd.DataFrame,n:int=3)->pd.DataFrame:
    discovered=discovery_for_hard_cases(identity,eod_universe,n_issuers=20)
    if discovered.empty:return discovered
    chosen=[]
    for cik,g in discovered.groupby("cik",sort=False):
        g=g.sort_values("discovery_score",ascending=False).reset_index(drop=True)
        top=float(g.loc[0,"discovery_score"]);second=float(g.loc[1,"discovery_score"]) if len(g)>1 else 0.
        if top>=.90 and top-second>=.08:
            r=g.loc[0].to_dict();r["candidate_basis"]="high-margin-discovery-access-test-only";chosen.append(r)
        if len(chosen)>=n:break
    return pd.DataFrame(chosen)

def run_depth_probe(identity:pd.DataFrame,token:str,n:int=3)->dict:
    adapter=EODHDProbeAdapter(token);universe=adapter.fetch_security_master()
    sample=choose_depth_probe(identity,universe,n);results=[]
    for _,r in sample.iterrows():
        start=str(pd.Timestamp(r["first_filing"]).date())
        end=str(min(pd.Timestamp(r["first_filing"])+pd.DateOffset(years=1),pd.Timestamp("2017-12-31")).date())
        prices=adapter.fetch_prices([r["security_id"]],start,end)
        results.append({"cik":r["cik"],"security_id":r["security_id"],"security_name":r["security_name"],
                        "discovery_score":float(r["discovery_score"]),"candidate_basis":r["candidate_basis"],
                        "requested_start":start,"requested_end":end,"rows":len(prices),
                        "first_price":str(pd.to_datetime(prices["date"]).min().date()) if len(prices) else None,
                        "last_price":str(pd.to_datetime(prices["date"]).max().date()) if len(prices) else None})
    return {"sample_size":len(sample),"results":results,
            "warning":"Candidates are discovery-only access tests and are not accepted CIK-security mappings."}
