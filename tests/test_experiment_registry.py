import pytest
from finrisk.evidence.experiment_registry import experiment_record

def test_registry_rejects_unknown_status():
    with pytest.raises(ValueError):experiment_record("x","m","winner","sha",{},{},"x")

def test_promoted_result_requires_rationale():
    with pytest.raises(ValueError):experiment_record("x","m","promoted","sha",{},{},"")
