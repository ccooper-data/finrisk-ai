import pandas as pd
from finrisk.modeling.robustness import yearly_metrics,subgroup_metrics

def test_year_without_both_classes_is_not_scored():
    f=pd.DataFrame({"filed":["2024-01-01","2024-02-01"],"distress_12m":[0,0],"score":[.1,.2]})
    assert yearly_metrics(f)["2024"]["status"]=="insufficient_classes"

def test_small_subgroup_is_not_overinterpreted():
    f=pd.DataFrame({"sector":["x"]*20,"distress_12m":[1]+[0]*19,"score":[.9]+[.1]*19})
    assert subgroup_metrics(f,"sector")["x"]["status"]=="insufficient_support"
