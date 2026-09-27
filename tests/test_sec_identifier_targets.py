import pandas as pd
import pytest
from finrisk.identity.sec_identifier_targets import select_identifier_targets,target_summary

def test_isin_targets_prioritize_high_margin_and_preserve_identifier():
    d=pd.DataFrame({"cik":["a","b","c"],"top_security_id":["A","B","C"],"top_score":[.99,.99,.8],
                    "margin":[.2,0,.3],"isin":["us0378331005","US5949181045",None],
                    "isin_present":[True,True,False],"is_delisted":[True,True,True]})
    o=select_identifier_targets(d)
    assert o["cik"].tolist()==["a","b"]
    assert o.loc[0,"target_priority"]=="A_high_margin_isin"
    assert o.loc[0,"isin"]=="US0378331005"
    assert target_summary(o)["targets"]==2

def test_targets_fail_closed_when_presence_flag_loses_identifier_value():
    d=pd.DataFrame({"cik":["a"],"top_security_id":["A"],"top_score":[.99],"margin":[.2],
                    "isin":[None],"isin_present":[True],"is_delisted":[True]})
    with pytest.raises(ValueError,match="marks ISIN present"):
        select_identifier_targets(d)
