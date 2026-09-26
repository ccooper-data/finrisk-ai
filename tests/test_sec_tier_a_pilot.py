import pandas as pd
from finrisk.identity.sec_tier_a_pilot import tier_a_pilot_plan,pilot_summary

def test_pilot_contains_only_tier_a_targets():
    t=pd.DataFrame({"cik":["1","2"],"top_security_id":["A","B"],
                    "target_priority":["A_high_margin_isin","B_strong_ambiguous_isin"]})
    p=pd.DataFrame({"cik":["1","1","2"],"candidate_security_id":["A","A","B"],
                    "filing_date":["2020-01-01","2019-01-01","2020-01-01"],"accession":["a","b","c"]})
    o=tier_a_pilot_plan(t,p)
    assert o["cik"].tolist()==["1","1"] and pilot_summary(o)["planned_accessions"]==2
