import pandas as pd
from finrisk.market.eodhd import EODHDProbeAdapter

def test_eodhd_capabilities_fail_closed_without_point_in_time_evidence():
    a=EODHDProbeAdapter("fake")
    c=a.capabilities
    assert c.historical_delisted and c.provenance
    assert not c.identifier_history
    assert not c.point_in_time_identifiers

def test_eodhd_security_master_does_not_fabricate_validity(monkeypatch):
    a=EODHDProbeAdapter("fake")
    monkeypatch.setattr(a,"_get",lambda path,params=None:[{"Code":"ABC","Name":"Acme","Isin":"US0378331005"}])
    d=a.fetch_security_master()
    assert d["valid_from"].isna().all()
    assert d["valid_to"].isna().all()
