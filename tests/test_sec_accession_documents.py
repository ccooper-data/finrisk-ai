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


def test_no_primary_metadata_falls_back_to_bounded_text_documents():
    docs=[
        {"name":"company-20101231x10k.htm","url":"https://www.sec.gov/Archives/edgar/data/1/abc/company-20101231x10k.htm"},
        {"name":"random.xml","url":"https://www.sec.gov/Archives/edgar/data/1/abc/random.xml"},
        {"name":"notes.txt","url":"https://www.sec.gov/Archives/edgar/data/1/abc/notes.txt"},
    ]
    selected=select_accession_documents(docs,None,8)
    assert [x["name"] for x in selected]==["company-20101231x10k.htm","notes.txt"]
    assert all(x["selection_reason"]=="textual_accession_fallback" for x in selected)
