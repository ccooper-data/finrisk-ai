import pandas as pd
from finrisk.market.eodhd_depth import choose_depth_probe

def test_depth_probe_requires_unique_exact_candidate():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[["ACME INC"]],"first_filing":["2010-01-01"],"last_filing":["2012-01-01"]})
    u=pd.DataFrame({"security_id":["A.US"],"security_name":["Acme, Inc."]})
    o=choose_depth_probe(i,u,1)
    assert len(o)==1 and o.loc[0,"security_id"]=="A.US"
