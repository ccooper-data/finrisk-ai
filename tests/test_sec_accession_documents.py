import pytest
from finrisk.identity.sec_accession_documents import select_accession_documents,validate_selected_urls

def test_selects_primary_and_ex2_ex4_text_only():
    docs=[{"name":"main.htm","url":"https://x/a/main.htm"},{"name":"ex4-1.htm","url":"https://x/a/ex4-1.htm"},
          {"name":"ex21.htm","url":"https://x/a/ex21.htm"},{"name":"ex2_1.txt","url":"https://x/a/ex2_1.txt"},
          {"name":"image.jpg","url":"https://x/a/image.jpg"}]
    o=select_accession_documents(docs,"main.htm")
    assert [x["name"] for x in o]==["main.htm","ex4-1.htm","ex2_1.txt"]

def test_selected_document_cannot_escape_accession():
    with pytest.raises(ValueError):validate_selected_urls([{"url":"https://x/other/a.htm"}],"https://x/a")
