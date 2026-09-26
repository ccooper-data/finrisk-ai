import pandas as pd,pytest
from finrisk.market.security_master import validate_security_master

BASE={"security_id":["s"],"issuer_id":["i"],"security_name":["Acme"],"valid_from":["2010-01-01"],"valid_to":["2015-01-01"],
      "source":["x"],"source_identifier":["1"]}

def test_invalid_security_interval_rejected():
    d=pd.DataFrame(dict(BASE,valid_from=["2016-01-01"]))
    with pytest.raises(ValueError):validate_security_master(d)

def test_valid_security_master_counts_entities():
    r=validate_security_master(pd.DataFrame(BASE))
    assert r["securities"]==1 and r["issuers"]==1
