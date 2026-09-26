import pandas as pd
from finrisk.identity.sec_filing_retrieval_plan import filing_retrieval_plan,retrieval_summary

def test_plan_is_bounded_and_prefers_core_filings():
    t=pd.DataFrame({"cik":["1"],"top_security_id":["A.US"],"target_priority":["A_high_margin_isin"]})
    f=pd.DataFrame({"cik":["1"]*3,"adsh":["a","b","c"],"filed":["2013-01-01","2012-01-01","2011-01-01"],
                    "form":["10-K","8-K","S-1"]})
    p=filing_retrieval_plan(t,f,2)
    assert p["accession"].tolist()==["a","b"] and retrieval_summary(p)["planned_filings"]==2
