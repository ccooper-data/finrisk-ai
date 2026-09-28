import numpy as np,pytest
from finrisk.modeling.cluster_bootstrap import paired_cik_cluster_bootstrap

def test_cluster_bootstrap_is_deterministic_and_resamples_clusters():
    y=np.array([0,1,0,0,1,0]);m=np.array([.1,.7,.1,.1,.7,.1]);b=np.full(6,1/3)
    c=np.array(["1","1","2","2","3","3"])
    a=paired_cik_cluster_bootstrap(y,m,b,c,replicates=200,seed=7)
    z=paired_cik_cluster_bootstrap(y,m,b,c,replicates=200,seed=7)
    assert a==z and a["unique_test_ciks"]==3
    assert a["scope"]["includes_retraining_uncertainty"] is False

def test_requires_complete_usable_ciks():
    with pytest.raises(ValueError,match="CIK"):
        paired_cik_cluster_bootstrap([0,1],[.1,.9],[.5,.5],["1","unavailable"],replicates=10)

def test_positive_difference_means_model_is_better():
    y=np.array([0,1,0,1]);m=np.array([.01,.99,.01,.99]);b=np.full(4,.5);c=np.array(["1","1","2","2"])
    r=paired_cik_cluster_bootstrap(y,m,b,c,replicates=100,seed=1)
    assert r["metrics"]["log_loss"]["baseline_minus_model"]>0
    assert r["metrics"]["brier"]["baseline_minus_model"]>0
