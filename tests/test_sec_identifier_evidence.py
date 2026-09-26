from finrisk.identity.sec_identifier_evidence import FilingDocument,collect_identifier_evidence,explode_identifier_evidence,is_priority_document

def test_priority_filing_preserves_identifier_provenance():
    d=FilingDocument("1","abc","2012-01-01","EX-4.1","https://sec/x","CUSIP 037833100")
    e=collect_identifier_evidence([d]);x=explode_identifier_evidence(e)
    assert x.loc[0,"identifier"]=="037833100" and x.loc[0,"accession"]=="abc"
    assert x.loc[0,"review_status"]=="unreviewed"

def test_exhibit_family_parser_does_not_confuse_ex2_with_ex21():
    assert is_priority_document("EX-2")
    assert is_priority_document("EX-2.1")
    assert is_priority_document("EX-4.12")
    assert not is_priority_document("EX-21")
    assert not is_priority_document("EX-24")

def test_nonpriority_document_is_not_scraped():
    d=FilingDocument("1","abc","2012-01-01","EX-21","https://sec/x","CUSIP 037833100")
    assert collect_identifier_evidence([d]).empty
