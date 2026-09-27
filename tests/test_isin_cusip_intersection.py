import pandas as pd
from finrisk.identity.isin_cusip_intersection import cusip_from_us_isin,identifier_intersection

def test_us_isin_exposes_embedded_cusip():
    assert cusip_from_us_isin("US0378331005")=="037833100"
    assert cusip_from_us_isin("GB0002634946") is None

def test_intersection_requires_multi_accession_exact_identifier():
    c=pd.DataFrame({"cik":["1","1"],"candidate_security_id":["A.US","A.US"],"identifier_type":["CUSIP","CUSIP"],
                    "identifier":["037833100","999999999"],"independent_accessions":[2,3]})
    t=pd.DataFrame({"cik":["1"],"top_security_id":["A.US"],"isin":["US0378331005"],"target_priority":["A_high_margin_isin"]})
    d,r=identifier_intersection(c,t)
    assert r["exact_cusip_matches"]==1 and r["targets_with_exact_match"]==1
    assert d.loc[d["identifier_match"],"review_status"].iloc[0]=="unreviewed"
