import io,zipfile
import pandas as pd
import pytest
from finrisk.identity.sec_fsds_names import quarter_url,normalize_cik

def test_sec_fsds_quarter_url_is_deterministic():
    assert quarter_url(2011,3).endswith("/2011q3.zip")

def test_cik_normalization_is_canonical():
    assert normalize_cik("123.0")=="0000000123"
    assert normalize_cik(123)=="0000000123"
    with pytest.raises(ValueError): normalize_cik("abc")

def test_unpublished_quarter_is_a_source_state(monkeypatch):
    import finrisk.identity.sec_fsds_names as m
    class R:
        status_code=404;content=b""
        def raise_for_status(self): raise AssertionError("404 should be handled")
    monkeypatch.setattr(m.httpx,"get",lambda *a,**k:R())
    df,e=m.fetch_sub(2099,4,"test@example.com")
    assert df.empty and e["status"]=="source_not_published" and e["matched_rows"]==0

def test_build_loop_survives_unpublished_quarter_and_matches_retrieved(tmp_path,monkeypatch):
    import finrisk.identity.sec_fsds_names as m
    sample=pd.DataFrame({"adsh":["x"],"cik":["0000000001"],"name":["ACME"],"filed":[pd.Timestamp("2010-01-01")]})
    calls={"n":0}
    def fake(year,q,ua):
        calls["n"]+=1
        if q==4:
            return pd.DataFrame(),{"year":year,"quarter":q,"status":"source_not_published","http_status":404,
                                  "source":"x","sha256":None,"bytes":0,"rows":0,"matched_rows":0}
        return sample.copy(),{"year":year,"quarter":q,"status":"retrieved","http_status":200,"source":"x",
                              "sha256":"x","bytes":1,"rows":1,"matched_rows":0}
    monkeypatch.setattr(m,"fetch_sub",fake)
    result=m.build_filing_names({"1"},2010,2010,tmp_path,"ua")
    out=pd.read_parquet(tmp_path/"sec_filing_names.parquet")
    assert calls["n"]==4 and result["retrieved_quarters"]==3
    assert result["matched_ciks"]==1 and result["total_matched_rows"]==3
    assert result["unpublished_quarters"]==[{"year":2010,"quarter":4,"http_status":404}]
    assert out["cik"].unique().tolist()==["0000000001"]

def test_zero_match_output_preserves_schema(tmp_path,monkeypatch):
    import finrisk.identity.sec_fsds_names as m
    sample=pd.DataFrame({"adsh":["x"],"cik":["0000000002"],"name":["OTHER"],"filed":[pd.Timestamp("2010-01-01")]})
    def fake(year,q,ua):
        return sample.copy(),{"year":year,"quarter":q,"status":"retrieved","http_status":200,"source":"x",
                              "sha256":"x","bytes":1,"rows":1,"matched_rows":0}
    monkeypatch.setattr(m,"fetch_sub",fake)
    result=m.build_filing_names({"1"},2010,2010,tmp_path,"ua")
    out=pd.read_parquet(tmp_path/"sec_filing_names.parquet")
    assert list(out.columns)==["adsh","cik","name","filed","form","period"]
    assert result["matched_ciks"]==0 and result["total_source_rows"]==4
