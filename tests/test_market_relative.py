import pandas as pd
from finrisk.market.relative import add_relative_market_features

def test_relative_return_uses_same_date_benchmark():
    dates=pd.date_range("2020-01-01",periods=300)
    s=pd.DataFrame({"security_id":["x"]*300,"date":dates,"close":range(100,400)})
    b=pd.DataFrame({"date":dates,"close":range(200,500)})
    o=add_relative_market_features(s,b)
    assert "excess_ret_63d" in o and len(o)==300
