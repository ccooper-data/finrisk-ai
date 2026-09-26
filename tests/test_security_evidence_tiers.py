import pandas as pd
from finrisk.identity.security_evidence_tiers import classify_security_evidence,tier_summary

def test_tiers_do_not_accept_security():
    d=pd.DataFrame({"top_score":[.99,.99,.75],"margin":[.2,0,.3],"isin_present":[True,True,False],
                    "is_delisted":[True,True,True],"candidate_count":[1,3,2]})
    o=classify_security_evidence(d)
    assert o["evidence_tier"].tolist()==["A_high_margin","B_strong_ambiguous","C_weak_needs_identifier"]
    assert not o["accepted_security"].any()
    assert tier_summary(o)["price_probe_eligible"]==1
