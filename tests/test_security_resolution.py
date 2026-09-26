from finrisk.identity.security_resolution import evaluate_candidate

BASE={"security_id":"s","security_name":"ACME CORP","valid_from":"2010-01-01","valid_to":"2015-12-31",
      "source":"provider","source_identifier":"x"}

def test_exact_name_without_identifier_stays_review():
    x=evaluate_candidate("1","ACME CORP","2011-01-01","2014-01-01",BASE)
    assert x.decision=="review_exact_name"

def test_strong_identifier_plus_overlap_accepts():
    c=dict(BASE,identifier_evidence=True)
    assert evaluate_candidate("1","ACME CORP","2011-01-01","2014-01-01",c).decision=="accepted_identifier"

def test_nonoverlap_rejects_even_strong_identifier():
    c=dict(BASE,identifier_evidence=True)
    assert evaluate_candidate("1","ACME CORP","2020-01-01","2021-01-01",c).decision=="rejected"
