import pandas as pd
from finrisk.market.probe import summarize_provider_probe

def test_probe_separates_resolution_from_price_coverage():
    s=pd.DataFrame({"cik":["1","2"],"probe_group":["hard","healthy"]})
    c=pd.DataFrame({"cik":["1","2"],"security_id":["a","b"],"decision":["accepted_identifier","accepted_identifier"]})
    p=pd.DataFrame({"security_id":["a"]})
    r=summarize_provider_probe(s,c,p)
    assert r["resolved_companies"]==2 and r["priced_companies"]==1
