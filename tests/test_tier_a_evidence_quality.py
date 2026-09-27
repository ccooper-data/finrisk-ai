import pandas as pd
from finrisk.identity.tier_a_evidence_quality import evidence_quality

def test_quality_separates_raw_rows_from_unique_identifiers():
    f=pd.DataFrame({"cik":["1","1"],"identifier_type":["CUSIP","CUSIP"],"identifier":["123456789","123456789"],
                    "common_equity_context":[True,True],"document_sha256":["a","b"],"security_context":["common_equity","common_equity"]})
    _,r=evidence_quality(f)
    assert r["rows"]==2 and r["unique_identifiers"]==1 and r["duplicate_rate"]==1.0
    assert r["targets_with_common_equity"]==1
