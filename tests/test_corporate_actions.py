import pandas as pd,pytest
from finrisk.market.corporate_actions import validate_corporate_actions

def test_unknown_corporate_action_rejected():
    d=pd.DataFrame({"security_id":["x"],"effective_date":["2020-01-01"],"action_type":["magic"],
                    "source":["s"],"source_identifier":["1"]})
    with pytest.raises(ValueError):validate_corporate_actions(d)

def test_symbol_change_supported():
    d=pd.DataFrame({"security_id":["x"],"effective_date":["2020-01-01"],"action_type":["symbol_change"],
                    "source":["s"],"source_identifier":["1"]})
    validate_corporate_actions(d)
