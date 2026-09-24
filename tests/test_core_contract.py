import pandas as pd
from finrisk.cohort_builder import CohortBuildConfig, quarters
from finrisk.labels import label_forward_distress
from finrisk.periods import build_period_matrix, select_period_correct_facts

def test_quarter_plan():
    assert [q.slug for q in quarters(CohortBuildConfig(start_year=2026,end_year=2026,end_quarter=2))]==["2026q1","2026q2"]

def test_forward_label_is_strictly_future():
    obs=pd.DataFrame({"cik":["1","1"],"filed":["2025-01-01","2025-12-31"]})
    ev=pd.DataFrame({"cik":["1"],"event_date":["2025-06-01"],"event_type":["sec_8k_item_1_03"]})
    out=label_forward_distress(obs,ev)
    assert out["distress_12m"].tolist()==[1,0]

def test_period_semantics_accept_valid_discrete_and_ytd_10q():
    f=pd.DataFrame({"adsh":["a","a"],"feature":["revenue","revenue"],"tag":["Revenues","Revenues"],"ddate":pd.to_datetime(["2025-06-30","2025-06-30"]),"period":pd.to_datetime(["2025-06-30","2025-06-30"]),"qtrs":[1,2],"form":["10-Q","10-Q"]})
    out=select_period_correct_facts(f)
    assert out["qtrs"].tolist()==[1,2]

def test_cik_types_are_normalized_before_label_join():
    obs=pd.DataFrame({"cik":[1234],"filed":["2025-01-01"]})
    ev=pd.DataFrame({"cik":["0000001234"],"event_date":["2025-06-01"],"event_type":["sec_8k_item_1_03"]})
    out=label_forward_distress(obs,ev)
    assert out["distress_12m"].tolist()==[1]
    assert out["days_to_distress"].tolist()==[151.0]

def test_q2_ytd_duration_is_preserved_when_discrete_missing():
    f=pd.DataFrame({"adsh":["q2"],"cik":[1],"form":["10-Q"],"period":pd.to_datetime(["2025-06-30"]),"filed":pd.to_datetime(["2025-08-01"]),"feature":["revenue"],"tag":["Revenues"],"ddate":pd.to_datetime(["2025-06-30"]),"qtrs":[2],"value":[200.0]})
    out=select_period_correct_facts(f)
    assert out["qtrs"].tolist()==[2]

def test_discrete_quarter_is_preferred_over_ytd_when_both_exist():
    f=pd.DataFrame({"adsh":["q2","q2"],"cik":[1,1],"form":["10-Q","10-Q"],"period":pd.to_datetime(["2025-06-30","2025-06-30"]),"filed":pd.to_datetime(["2025-08-01","2025-08-01"]),"feature":["revenue","revenue"],"tag":["Revenues","Revenues"],"ddate":pd.to_datetime(["2025-06-30","2025-06-30"]),"qtrs":[1,2],"value":[110.0,200.0]})
    wide=build_period_matrix(f)
    assert wide.loc[0,"revenue"]==110.0
