import pandas as pd
from finrisk.identity.fsds_discovery_impact import compare_discovery

def test_filing_alias_can_create_candidate_without_accepting_identity():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[["OLD UNRELATED NAME"]],"first_filing":["2010-01-01"]})
    f=pd.DataFrame({"cik":["0000000001"],"name":["ACME HOLDINGS INC"]})
    u=pd.DataFrame({"security_id":["A.US"],"security_name":["Acme Holdings"],"isin":["X"],"is_delisted":[True]})
    d,r=compare_discovery(i,f,u,.45,1)
    assert r["before_with_candidate"]==0 and r["after_with_candidate"]==1 and r["new_candidate_issuers"]==1
    assert "decision" not in d.columns
