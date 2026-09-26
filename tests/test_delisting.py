import pandas as pd,pytest
from finrisk.market.delisting import validate_delistings,apply_delisting_returns

def test_delisting_requires_provenance_and_return():
    with pytest.raises(ValueError):validate_delistings(pd.DataFrame({"security_id":["x"]}))

def test_delisting_event_is_explicit():
    d=pd.DataFrame({"security_id":["x"],"delist_date":["2020-01-02"],"delist_code":[500],"delist_return":[-.8],
                    "source":["s"],"source_identifier":["id"]})
    e=apply_delisting_returns(pd.DataFrame(),d)
    assert e.loc[0,"delist_return"]==-.8 and bool(e.loc[0,"is_delisting_observation"])
