import pandas as pd
from finrisk.identity.fsds_hardcase import hardcase_frame,incremental_identity_report

def test_hardcase_selector_prioritizes_distress_without_ticker():
    f=pd.DataFrame({"cik":["a","b"],"distress_observations":[1,1],"has_current_ticker":[False,True],
                    "first_filing":["2010-01-01","2009-01-01"],"last_filing":["2012-01-01","2012-01-01"]})
    assert hardcase_frame(f,10)["cik"].tolist()==["a"]

def test_out_of_scope_is_not_counted_as_source_miss():
    i=pd.DataFrame({"cik":["1","2"],"first_filing":["2005-01-01","2010-01-01"],"last_filing":["2008-01-01","2012-01-01"],
                    "historical_names":[["OLD"],["ACME"]]})
    n=pd.DataFrame({"cik":["2"],"name":["ACME NEW"]})
    d,r=incremental_identity_report(i,n)
    assert r["out_of_scope"]==1 and r["eligible_missing"]==0 and r["with_incremental_names"]==1


def test_incremental_report_normalizes_cik_on_both_sides():
    i=pd.DataFrame({"cik":["2.0"],"first_filing":["2010-01-01"],"last_filing":["2012-01-01"],
                    "historical_names":[["ACME"]]})
    n=pd.DataFrame({"cik":["0000000002"],"name":["ACME NEW"]})
    _,r=incremental_identity_report(i,n)
    assert r["eligible_observed"]==1 and r["with_incremental_names"]==1
