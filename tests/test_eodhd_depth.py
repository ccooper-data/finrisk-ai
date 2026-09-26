import pandas as pd
from finrisk.market.eodhd_depth import choose_depth_probe

def test_depth_probe_can_use_high_margin_fuzzy_candidate():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[["INTERNATIONAL BUSINESS MACHINES CORP"]],"first_filing":["2010-01-01"],"last_filing":["2012-01-01"]})
    u=pd.DataFrame({"security_id":["A.US","B.US"],"security_name":["International Business Machines","Totally Different Co"],
                    "isin":["X","Y"],"is_delisted":[True,True]})
    o=choose_depth_probe(i,u,1)
    assert len(o)==1 and o.loc[0,"security_id"]=="A.US" and "access-test-only" in o.loc[0,"candidate_basis"]
