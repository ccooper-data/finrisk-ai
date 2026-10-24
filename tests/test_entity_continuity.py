import pytest
from finrisk.identity.continuity import EntityContinuityEvidence,validate_continuity

def test_successor_requires_distinct_cik_and_date():
    with pytest.raises(ValueError):
        validate_continuity(EntityContinuityEvidence("1","1","successor","2020-01-01","s","x","note"))
    with pytest.raises(ValueError):
        validate_continuity(EntityContinuityEvidence("1","2","successor",None,"s","x","note"))

def test_same_registrant_can_remain_same_cik():
    validate_continuity(EntityContinuityEvidence("1","1","same_registrant",None,"SEC","x","same filer"))
