from finrisk.identity.sec_identifier_evidence import FilingDocument,collect_identifier_evidence,explode_identifier_evidence

def test_priority_filing_preserves_identifier_provenance():
    d=FilingDocument("1","abc","2012-01-01","EX-4.1","https://sec/x","CUSIP 037833100")
    e=collect_identifier_evidence([d]);x=explode_identifier_evidence(e)
    assert x.loc[0,"identifier"]=="037833100" and x.loc[0,"accession"]=="abc"
    assert x.loc[0,"review_status"]=="unreviewed"

def test_nonpriority_document_is_not_scraped():
    d=FilingDocument("1","abc","2012-01-01","EX-21","https://sec/x","CUSIP 037833100")
    assert collect_identifier_evidence([d]).empty
