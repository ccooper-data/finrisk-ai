import numpy as np
import pandas as pd
from finrisk.modeling.sequences import SequenceConfig,build_sequence_arrays

def test_sequences_use_only_current_and_prior_company_rows():
    dates=pd.to_datetime(["2019-03-01","2019-06-01","2021-03-01","2021-06-01","2023-03-01","2023-06-01"])
    f=pd.DataFrame({"cik":["1"]*6,"adsh":[f"a{i}" for i in range(6)],"filed":dates,
                    "distress_12m":[0,0,0,1,0,1],"assets":[1,2,3,4,5,6],
                    "liabilities":[1,1,2,2,3,3],"roa":[.1,.2,.3,.4,.5,.6]})
    seq,y,masks,lengths,meta=build_sequence_arrays(f,config=SequenceConfig(lookback=4,min_history=2))
    assert len(y)==5
    assert lengths.tolist()==[2,3,4,4,4]
    assert meta["split_rows"]=={"train":1,"validation":2,"test":2}
    assert seq.shape[1]==4
    assert np.isfinite(seq).all()
