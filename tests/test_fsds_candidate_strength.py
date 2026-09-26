import pandas as pd
from finrisk.identity.fsds_candidate_strength import candidate_strength

def test_strength_reports_margin_and_identifier_presence():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[[]],"first_filing":["2010-01-01"]})
    f=pd.DataFrame({"cik":["0000000001"],"name":["ACME HOLDINGS INC"]})
    u=pd.DataFrame({"security_id":["A.US","B.US"],"security_name":["Acme Holdings","Acme Holdings Preferred"],
                    "isin":["US1",None],"is_delisted":[True,True]})
    d,r=candidate_strength(i,f,u,.45,1)
    assert r["with_candidate"]==1 and bool(d.loc[0,"isin_present"]) and d.loc[0,"margin"] is not None
