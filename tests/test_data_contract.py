import pandas as pd,pytest
from finrisk.evidence.data_contract import dataframe_contract

def test_contract_rejects_missing_required_column():
    with pytest.raises(ValueError):dataframe_contract(pd.DataFrame({"a":[1]}),["a","b"])

def test_contract_rejects_duplicate_key():
    with pytest.raises(ValueError):dataframe_contract(pd.DataFrame({"id":[1,1]}),["id"],["id"])
