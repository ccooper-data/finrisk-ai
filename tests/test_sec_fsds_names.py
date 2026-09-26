from finrisk.identity.sec_fsds_names import quarter_url

def test_sec_fsds_quarter_url_is_deterministic():
    assert quarter_url(2011,3).endswith("/2011q3.zip")


def test_unpublished_quarter_is_a_source_state(monkeypatch):
    import finrisk.identity.sec_fsds_names as m
    class R:
        status_code=404
        content=b""
        def raise_for_status(self): raise AssertionError("404 should be handled")
    monkeypatch.setattr(m.httpx,"get",lambda *a,**k:R())
    df,e=m.fetch_sub(2099,4,"test@example.com")
    assert df.empty and e["status"]=="source_not_published" and e["http_status"]==404
