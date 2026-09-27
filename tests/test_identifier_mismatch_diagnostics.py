import pandas as pd
from finrisk.identity.identifier_mismatch_diagnostics import mismatch_diagnostics

def test_classifies_identifier_relationships_without_promoting():
    d=pd.DataFrame({
        "cik":["1","1","2","3"],
        "identifier":["037833100","037833101","037833250","999999999"],
        "candidate_cusip":["037833100","037833100","037833100","037833100"],
        "identifier_match":[True,False,False,False],
    })
    out,r=mismatch_diagnostics(d)
    assert out["relationship"].tolist()==[
        "exact",
        "same_security_body_check_digit_difference",
        "same_issuer_root_different_issue",
        "different_issuer_root",
    ]
    assert r["rows"]==4 and r["issuers"]==3
