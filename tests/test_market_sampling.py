import pandas as pd
from finrisk.market.sampling import provider_probe_sample

def test_probe_prioritizes_distressed_without_current_ticker():
    f=pd.DataFrame({"cik":["a","b","c"],"distress_observations":[2,1,0],"observations":[10,5,20],
                    "has_current_ticker":[False,True,True]})
    o=provider_probe_sample(f,1,1)
    assert o.iloc[0]["cik"]=="a" and o.iloc[0]["probe_group"]=="distressed_no_current_ticker"
