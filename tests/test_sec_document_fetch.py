import pytest
from finrisk.identity.sec_document_fetch import fetch_document

class R:
    status_code=200
    content=b"<html><body>CUSIP 037833100 common stock</body></html>"
    text=content.decode()
    def raise_for_status(self):pass
class C:
    def get(self,url):return R()
    def close(self):pass

def test_fetch_hashes_and_flattens_html():
    text,e=fetch_document("https://sec/a/x.htm","ua","https://sec/a",C())
    assert "CUSIP 037833100 common stock" in text and e["sha256"] and e["bytes"]>0

def test_fetch_rejects_url_outside_accession():
    with pytest.raises(ValueError):fetch_document("https://sec/b/x.htm","ua","https://sec/a",C())
