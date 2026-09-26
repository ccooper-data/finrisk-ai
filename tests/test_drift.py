import numpy as np,pandas as pd
from finrisk.modeling.drift import population_stability_index,feature_drift

def test_identical_distribution_has_near_zero_psi():
    x=np.arange(1000)
    assert population_stability_index(x,x)<1e-9

def test_shifted_distribution_has_positive_psi():
    assert population_stability_index(np.arange(1000),np.arange(1000)+500)>0
