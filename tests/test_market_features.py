import pandas as pd
from finrisk.market.features import engineer_market_history,attach_market_asof

def test_market_join_is_backward_only():
    prices=pd.DataFrame({"security_id":["x"]*300,"date":pd.date_range("2023-01-01",periods=300),
                         "close":range(100,400),"volume":range(1000,1300)})
    feat=engineer_market_history(prices)
    filing=pd.DataFrame({"security_id":["x"],"filed":[pd.Timestamp("2023-08-01")]})
    out=attach_market_asof(filing,feat)
    assert out.loc[0,"date"]<=out.loc[0,"filed"]

def test_market_features_are_trailing_only():
    prices=pd.DataFrame({"security_id":["x"]*300,"date":pd.date_range("2023-01-01",periods=300),
                         "close":range(100,400),"volume":range(1000,1300)})
    a=engineer_market_history(prices.iloc[:250].copy())
    b=engineer_market_history(prices.copy())
    d=prices.iloc[249]["date"]
    cols=["ret_21d","ret_63d","vol_63d","drawdown_252d"]
    for c in cols:assert a.loc[a.date.eq(d),c].iloc[0]==b.loc[b.date.eq(d),c].iloc[0]
