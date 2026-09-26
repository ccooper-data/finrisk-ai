import pandas as pd
from finrisk.identity.resolution import normalize_entity_name,candidate_score,classify_candidate
from finrisk.market.provider import validate_security_candidates

def test_name_normalization_is_deterministic():
    assert normalize_entity_name("Acme Holdings, Inc.")=="ACME HOLDINGS"

def test_name_similarity_never_auto_accepts_without_identifier():
    assert classify_candidate(1.0,True,False)=="review_exact_name"
    assert classify_candidate(1.0,True,True)=="accepted_identifier"

def test_no_date_overlap_is_rejected():
    assert classify_candidate(1.0,False,True)=="rejected"

def test_market_provider_requires_provenance():
    df=pd.DataFrame({"security_id":["x"]})
    try:validate_security_candidates(df)
    except ValueError as e:assert "source" in str(e)
    else:raise AssertionError("expected provenance validation failure")
