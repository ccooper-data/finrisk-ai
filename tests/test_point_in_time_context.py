import pandas as pd
from finrisk.features.context import point_in_time_join

def test_context_join_never_uses_future_observations():
    filings=pd.DataFrame({"cik":["1"],"filed":["2024-02-15"],"adsh":["a"]})
    prices=pd.DataFrame({"cik":["1"]*300,"date":pd.date_range("2023-01-01",periods=300),"close":range(100,400),"volume":range(1000,1300)})
    macro=pd.DataFrame({"date":pd.to_datetime(["2024-01-31","2024-03-31"]),"treasury_3m":[5.0,9.0],"treasury_10y":[4.0,9.5],
                        "unemployment":[4.0,9.0],"cpi":[300,400],"industrial_production":[100,50],"credit_spread":[1.2,9.0]})
    out=point_in_time_join(filings,prices,macro)
    assert out.loc[0,"treasury_3m"]==5.0
    assert out.loc[0,"unemployment"]==4.0
    assert out.loc[0,"date_macro"]==pd.Timestamp("2024-01-31")
