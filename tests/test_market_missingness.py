import pandas as pd,pytest
from finrisk.market.missingness import add_market_missingness_indicators,require_no_market_row_drop

def test_unmatched_market_rows_are_retained():
    f=pd.DataFrame({"id":[1,2],"ret_21d":[.1,None]})
    o=add_market_missingness_indicators(f,["ret_21d"])
    assert len(o)==2 and not bool(o.loc[1,"market_data_available"]) and o.loc[1,"ret_21d__missing"]==1

def test_market_join_cannot_change_population():
    with pytest.raises(ValueError):require_no_market_row_drop(pd.DataFrame({"x":[1,2]}),pd.DataFrame({"x":[1]}))
