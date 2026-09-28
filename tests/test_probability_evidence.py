import numpy as np
from finrisk.modeling.probability_evidence import probability_evidence

def test_calibrator_fits_validation_and_reports_test_probability_quality():
    yv=np.array([0]*90+[1]*10)
    pv=np.array([.20]*90+[.80]*10)
    yt=np.array([0]*90+[1]*10)
    pt=np.array([.25]*90+[.75]*10)
    r=probability_evidence(yv,pv,yt,pt,"platt")
    assert r["fit_partition"]=="validation"
    assert r["evaluation_partition"]=="test"
    assert r["probability_quality"]["calibrated_brier"] < r["probability_quality"]["raw_brier"]
    assert "base_rate_brier" in r["probability_quality"]

def test_test_labels_do_not_fit_calibrator():
    yv=np.array([0,0,0,1,1,1]);pv=np.array([.1,.2,.3,.7,.8,.9])
    yt=np.array([1,1,1,0,0,0]);pt=np.array([.1,.2,.3,.7,.8,.9])
    r=probability_evidence(yv,pv,yt,pt,"platt")
    assert r["fit_partition"]=="validation"
    assert r["test_positives"]==3
