import pandas as pd
from finrisk.market.coverage import market_coverage_report

def test_market_coverage_reports_positive_loss():
    f=pd.DataFrame({"filed":["2024-01-01"]*4,"distress_12m":[1,1,0,0],"m":[1,None,1,None]})
    r=market_coverage_report(f,["m"])
    assert r["row_coverage"]==.5 and r["positive_coverage"]==.5
