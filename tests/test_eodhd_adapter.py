from finrisk.market.eodhd import EODHDProbeAdapter

def test_eodhd_documented_capability_shape():
    a=EODHDProbeAdapter("fake")
    c=a.capabilities
    assert c.historical_delisted and c.identifier_history and c.point_in_time_identifiers and c.provenance
