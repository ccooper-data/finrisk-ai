import pandas as pd
from finrisk.identity.sec_identifier_targets import select_identifier_targets,target_summary

def test_isin_targets_prioritize_high_margin_without_acceptance():
    d=pd.DataFrame({"cik":["a","b","c"],"top_security_id":["A","B","C"],"top_score":[.99,.99,.8],
                    "margin":[.2,0,.3],"isin_present":[True,True,False],"is_delisted":[True,True,True]})
    o=select_identifier_targets(d)
    assert o["cik"].tolist()==["a","b"]
    assert o.loc[0,"target_priority"]=="A_high_margin_isin"
    assert target_summary(o)["targets"]==2
