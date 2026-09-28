from finrisk.identity.sec_13f_pdf import parse_official_13f_pdf_text

def test_historical_pdf_row_reconstructs_and_validates_cusip():
    d=parse_official_13f_pdf_text("G0129K 10 4 * AIRCASTLE LTD COM")
    assert d.loc[0,"cusip"]=="G0129K104"

def test_invalid_grouped_token_is_rejected():
    assert parse_official_13f_pdf_text("G0129K 10 5 AIRCASTLE LTD COM").empty

def test_headers_and_prose_are_ignored():
    assert parse_official_13f_pdf_text("CUSIP NO ISSUER NAME ISSUER DESCRIPTION STATUS\nRun Date: 1/8/2010").empty
