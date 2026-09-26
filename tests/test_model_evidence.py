import pytest
from finrisk.evidence.model_card import model_evidence,validate_model_evidence

def test_model_evidence_requires_frozen_data_and_test_metrics():
    e=model_evidence("x","pytorch",{"sec":"sha256:abc"},{"train_end":"2020-12-31"},["roa"],{"test":{"pr_auc":.1}},"deadbeef")
    validate_model_evidence(e)
    bad=dict(e);bad["data_artifacts"]={}
    with pytest.raises(ValueError):validate_model_evidence(bad)
    bad=dict(e);bad["metrics"]={"train":{}}
    with pytest.raises(ValueError):validate_model_evidence(bad)
