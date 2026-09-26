import pytest
from finrisk.evidence.promotion import promotion_gate,require_promotion

BASE={"data_artifacts":{"x":"sha"},"metrics":{"test":{"pr_auc":.1}},"code_sha":"abc","limitations":[]}
EXP={"status":"candidate"}

def test_market_requires_survivorship_gate():
    assert not promotion_gate(BASE,EXP,{"market_model":True})["passed"]

def test_current_vintage_macro_cannot_promote():
    with pytest.raises(ValueError):require_promotion(BASE,EXP,{"current_vintage_macro":True})

def test_clean_candidate_can_pass():
    assert promotion_gate(BASE,EXP)["passed"]
