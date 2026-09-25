import pandas as pd
import pytest
from finrisk.modeling.baseline import TemporalSplit, temporal_split

def frame():
    return pd.DataFrame({
        "filed":["2019-01-01","2020-12-31","2021-01-01","2022-12-31","2023-01-01","2026-01-01"],
        "distress_12m":[0,1,0,1,0,1],
    })

def test_temporal_split_has_strict_boundaries():
    train,val,test=temporal_split(frame())
    assert train["filed"].max()==pd.Timestamp("2020-12-31")
    assert val["filed"].min()==pd.Timestamp("2021-01-01")
    assert val["filed"].max()==pd.Timestamp("2022-12-31")
    assert test["filed"].min()==pd.Timestamp("2023-01-01")

def test_temporal_split_fails_if_partition_empty():
    with pytest.raises(ValueError,match="nonempty"):
        temporal_split(frame(),TemporalSplit("2025-12-31","2026-12-31"))
