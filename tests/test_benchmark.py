import pandas as pd,pytest
from finrisk.market.benchmark import validate_benchmark

def test_mixed_benchmark_identity_rejected():
    d=pd.DataFrame({"date":["2024-01-01","2024-01-02"],"close":[1,2],"benchmark_id":["a","b"],"source":["s","s"],"retrieved_at":["x","x"]})
    with pytest.raises(ValueError):validate_benchmark(d)
