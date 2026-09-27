import pandas as pd
from finrisk.identity.tier_a_corroboration import corroboration_candidates

def test_corroboration_counts_independent_accessions_not_raw_duplicates():
    f=pd.DataFrame({"cik":["1","1","1"],"identifier_type":["CUSIP"]*3,"identifier":["123456789"]*3,
                    "candidate_security_id":["A.US"]*3,"common_equity_context":[True]*3,
                    "document_sha256":["a","a","b"],"accession":["x","x","y"],
                    "filing_date":["2010-01-01","2010-01-01","2011-01-01"]})
    d,r=corroboration_candidates(f)
    assert len(d)==1 and d.loc[0,"independent_accessions"]==2 and r["multi_accession"]==1
