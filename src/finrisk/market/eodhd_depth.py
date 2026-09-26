from __future__ import annotations
import os
import pandas as pd
from finrisk.market.eodhd import EODHDProbeAdapter
from finrisk.identity.resolution import normalize_entity_name

def choose_depth_probe(identity:pd.DataFrame,eod_universe:pd.DataFrame,n:int=3)->pd.DataFrame:
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    rows=[]
    # Candidate discovery only: exact normalized historical name, then require unique EODHD candidate.
    for _,r in hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).iterrows():
        aliases=r["historical_names"] if isinstance(r["historical_names"],list) else []
        norms={normalize_entity_name(x) for x in aliases}
        cand=eod_universe[eod_universe["security_name"].map(normalize_entity_name).isin(norms)]
        if len(cand)==1:
            x=cand.iloc[0]
            rows.append({"cik":r["cik"],"security_id":x["security_id"],"security_name":x["security_name"],
                         "first_filing":str(pd.Timestamp(r["first_filing"]).date()),"last_filing":str(pd.Timestamp(r["last_filing"]).date()),
                         "candidate_basis":"unique_exact_normalized_name"})
        if len(rows)>=n:break
    return pd.DataFrame(rows)

def run_depth_probe(identity:pd.DataFrame,token:str,n:int=3)->dict:
    adapter=EODHDProbeAdapter(token);universe=adapter.fetch_security_master()
    sample=choose_depth_probe(identity,universe,n)
    results=[]
    for _,r in sample.iterrows():
        start=r["first_filing"];end=min(str(pd.Timestamp(r["first_filing"])+pd.DateOffset(years=1))[:10],"2017-12-31")
        prices=adapter.fetch_prices([r["security_id"]],start,end)
        results.append({"cik":r["cik"],"security_id":r["security_id"],"requested_start":start,"requested_end":end,
                        "rows":len(prices),"first_price":str(pd.to_datetime(prices["date"]).min().date()) if len(prices) else None,
                        "last_price":str(pd.to_datetime(prices["date"]).max().date()) if len(prices) else None})
    return {"sample_size":len(sample),"results":results}
