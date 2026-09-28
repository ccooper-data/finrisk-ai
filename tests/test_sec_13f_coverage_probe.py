import pandas as pd
from finrisk.identity.sec_13f_coverage_probe import list_name_key,observation_quarters,select_five_cases,name_hits

def test_list_name_key_abbreviates_and_truncates():
    assert list_name_key("American Safety Insurance Holdings Limited")=="AMERICAN SAFETY INSURANCE HL"

def test_observation_quarters_back_series():
    assert observation_quarters("2012-08-01")==[(2012,3),(2011,3),(2010,3),(2009,3)]

def test_five_cases_are_deterministic_and_span_sorted_range():
    d=pd.DataFrame({"cik":[str(i) for i in range(9)],"last_filing":pd.date_range("2010-01-01",periods=9,freq="YS")})
    a=select_five_cases(d);b=select_five_cases(d.sample(frac=1,random_state=1))
    assert a["cik"].tolist()==b["cik"].tolist()
    assert a.iloc[0]["cik"]=="0" and a.iloc[-1]["cik"]=="8"

def test_exact_discovery_key_only_reports_hit():
    r=name_hits(["Acme Holdings Incorporated"],["ACME HLDGS INC"])
    assert r["exact_hit"]
