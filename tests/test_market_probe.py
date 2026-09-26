import pandas as pd
from finrisk.market.probe import evaluate_probe

def test_probe_separates_hard_case_coverage():
    p=pd.DataFrame({"cik":["a","b"],"probe_group":["distressed_no_current_ticker","nondistressed"]})
    r=pd.DataFrame({"cik":["a","b"],"security_id":["s1","s2"],"security_resolution":["accepted","accepted"]})
    prices=pd.DataFrame({"security_id":["s2"]})
    x=evaluate_probe(p,r,prices)
    assert x["groups"]["distressed_no_current_ticker"]["price_coverage"]==0
    assert x["groups"]["nondistressed"]["price_coverage"]==1
