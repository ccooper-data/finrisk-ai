import pandas as pd
from finrisk.identity.fsds_hardcase import hardcase_ciks

def test_hardcase_selector_prioritizes_distress_without_ticker():
    f=pd.DataFrame({"cik":["a","b"],"distress_observations":[1,1],"has_current_ticker":[False,True],
                    "first_filing":["2010-01-01","2009-01-01"]})
    assert hardcase_ciks(f,10)==["a"]
