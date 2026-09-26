import pandas as pd
from finrisk.market.security_join import attach_security_asof

def test_future_security_link_cannot_attach_to_earlier_filing():
    f=pd.DataFrame({"cik":["1"],"filed":["2015-01-01"]})
    l=pd.DataFrame({"cik":["1"],"security_id":["s"],"valid_from":["2016-01-01"],"valid_to":["2020-01-01"],"decision":["accepted_identifier"]})
    o=attach_security_asof(f,l)
    assert pd.isna(o.loc[0,"security_id"]) and o.loc[0,"security_resolution"]=="unresolved"

def test_multiple_active_accepted_links_are_ambiguous():
    f=pd.DataFrame({"cik":["1"],"filed":["2017-01-01"]})
    l=pd.DataFrame({"cik":["1","1"],"security_id":["a","b"],"valid_from":["2016-01-01"]*2,"valid_to":["2020-01-01"]*2,
                    "decision":["accepted_identifier"]*2})
    assert attach_security_asof(f,l).loc[0,"security_resolution"]=="ambiguous"
