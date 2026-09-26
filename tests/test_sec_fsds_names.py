import pandas as pd
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


def test_empty_match_output_preserves_cik_schema(tmp_path,monkeypatch):
    import finrisk.identity.sec_fsds_names as m
    sample=pd.DataFrame({"cik":["0000000002"],"name":["OTHER"],"adsh":["x"],"filed":[pd.Timestamp("2010-01-01")]})
    def fake(*a,**k):
        return sample.copy(),{"year":2010,"quarter":1,"status":"retrieved","http_status":200,"rows":1,"matched_rows":0}
    monkeypatch.setattr(m,"fetch_sub",fake)
    result=m.build_filing_names({"1"},2010,2010,tmp_path,"ua")
    out=pd.read_parquet(tmp_path/"sec_filing_names.parquet")
    assert "cik" in out.columns and result["matched_ciks"]==0 and result["total_source_rows"]==4
