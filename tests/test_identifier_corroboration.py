from finrisk.identity.identifier_corroboration import extract_identifiers,corroborate_candidate

def test_extracts_labeled_security_identifiers_from_text():
    x=extract_identifiers("CUSIP 037833100 and ISIN US0378331005")
    assert "037833100" in x["cusips"] and "US0378331005" in x["isins"]

def test_us_isin_can_be_corroborated_by_embedded_cusip():
    r=corroborate_candidate("US0378331005",[],["037833100"])
    assert r["identifier_corroborated"] and r["isin_embedded_cusip_match"]

def test_name_similarity_never_counts_as_identifier_evidence():
    assert not corroborate_candidate(None,[],[])["identifier_corroborated"]
