import pandas as pd,pytest
from finrisk.market.quality import validate_price_history

BASE={"security_id":["x"],"date":["2024-01-01"],"close":[10.],"volume":[100.],"source":["s"],"retrieved_at":["2024-01-02"]}

def test_nonpositive_price_rejected():
    d=pd.DataFrame(dict(BASE,close=[0.]))
    with pytest.raises(ValueError):validate_price_history(d)

def test_valid_price_history_reports_security_count():
    assert validate_price_history(pd.DataFrame(BASE))["securities"]==1
