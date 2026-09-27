from finrisk.identity.sec_accession_fetch import accession_base_url,accession_documents

def test_accession_url_normalization():
    assert accession_base_url("0000000123","0000123-20-000001").endswith("/123/000012320000001")

def test_index_document_urls_are_bounded_to_accession():
    p={"directory":{"item":[{"name":"a.htm","size":10},{"name":"b.txt","size":20}]}}
    d=accession_documents(p,"https://sec/accession")
    assert [x["url"] for x in d]==["https://sec/accession/a.htm","https://sec/accession/b.txt"]
