import numpy as np
import pandas as pd
from finrisk.modeling.boosted_tree import train_boosted_tree

def test_boosted_tree_preserves_temporal_populations():
    rng=np.random.default_rng(42)
    dates=pd.date_range("2018-01-01","2024-12-31",periods=500)
    f=pd.DataFrame({"filed":dates,"distress_12m":([0]*480+[1]*20)})
    rng.shuffle(f["distress_12m"].values)
    for name in ["current_ratio","liabilities_to_assets","roa","roe"]:
        f[name]=rng.normal(size=len(f))
    _,_,metrics,config=train_boosted_tree(f)
    assert sum(x["rows"] for x in metrics.values())==500
    assert metrics["test"]["rows"]>0 and metrics["validation"]["rows"]>0
    assert config["positive_weight"]>1
