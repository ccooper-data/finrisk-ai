from finrisk.identity.sec_fsds_names import quarter_url

def test_sec_fsds_quarter_url_is_deterministic():
    assert quarter_url(2011,3).endswith("/2011q3.zip")
