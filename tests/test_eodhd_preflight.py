import pytest
from finrisk.market.eodhd_preflight import eodhd_access_preflight

def test_eodhd_preflight_requires_token():
    with pytest.raises(ValueError):eodhd_access_preflight("")
