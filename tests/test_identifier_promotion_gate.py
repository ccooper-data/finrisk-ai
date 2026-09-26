from finrisk.identity.identifier_promotion_gate import IdentifierEvidence,identifier_promotion_gate

def test_exact_identifier_in_common_equity_context_can_reach_review():
    e=IdentifierEvidence(True,"common_equity",True,"2015-01-01","2010-01-01","2020-01-01")
    assert identifier_promotion_gate(e)["eligible_for_security_acceptance_review"]

def test_debt_identifier_is_blocked_even_if_exact():
    e=IdentifierEvidence(True,"debt",True,"2015-01-01","2010-01-01","2020-01-01")
    assert not identifier_promotion_gate(e)["eligible_for_security_acceptance_review"]

def test_future_security_is_blocked():
    e=IdentifierEvidence(True,"common_equity",True,"2015-01-01","2016-01-01","2020-01-01")
    assert not identifier_promotion_gate(e)["eligible_for_security_acceptance_review"]

def test_ambiguity_blocks_promotion():
    e=IdentifierEvidence(True,"common_equity",True,"2015-01-01",None,None,True)
    assert not identifier_promotion_gate(e)["eligible_for_security_acceptance_review"]
