from finrisk.identity.identifier_corroboration import extract_identifiers,corroborate_candidate,valid_cusip,valid_isin

def test_extracts_labeled_checksum_valid_security_identifiers():
    x=extract_identifiers("CUSIP No. 037833100 and ISIN US0378331005")
    assert x["cusips"]==["037833100"]
    assert x["isins"]==["US0378331005"]

def test_unlabeled_words_markup_amounts_and_invalid_tokens_are_rejected():
    text='FINANCIAL CONDITION QUARTERLY <ix:nonFraction id="c86277404"> common stock $102,937,000 SENIORNOTES8 ASOF8DEC2009'
    assert extract_identifiers(text)=={"cusips":[],"isins":[]}

def test_labeled_but_bad_check_digit_is_rejected():
    assert extract_identifiers("CUSIP No. 037833101 ISIN US0378331004")=={"cusips":[],"isins":[]}

def test_isin_requires_real_country_code_and_luhn():
    assert valid_isin("US0378331005")
    assert not valid_isin("FP0378331005")
    assert not valid_isin("SENIORNOTES8")

def test_cusip_checksum():
    assert valid_cusip("037833100")
    assert not valid_cusip("C86277404")
    assert not valid_cusip("102937000")

def test_us_isin_can_be_corroborated_by_valid_embedded_cusip():
    r=corroborate_candidate("US0378331005",[],["037833100"])
    assert r["identifier_corroborated"] and r["isin_embedded_cusip_match"]

def test_invalid_evidence_cannot_corroborate_candidate():
    r=corroborate_candidate("US0378331005",["US0378331004"],["C86277404"])
    assert not r["identifier_corroborated"]

def test_name_similarity_never_counts_as_identifier_evidence():
    assert not corroborate_candidate(None,[],[])["identifier_corroborated"]
