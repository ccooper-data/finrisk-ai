import pandas as pd
from finrisk.identity.candidate_discovery import name_similarity,discover_candidates

def test_fuzzy_discovery_handles_name_variation():
    assert name_similarity("INTERNATIONAL BUSINESS MACHINES CORP","International Business Machines")>.9

def test_discovery_is_explicitly_not_acceptance():
    u=pd.DataFrame({"security_id":["A.US"],"security_name":["Acme Holdings"],"isin":["X"],"is_delisted":[True]})
    d=discover_candidates("1",["ACME HOLDINGS INC"],u)
    assert len(d)==1 and bool(d.loc[0,"discovery_only"])
