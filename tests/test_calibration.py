import numpy as np
from finrisk.modeling.calibration import ProbabilityCalibrator,calibration_report

def test_calibrator_outputs_probabilities():
    p=np.linspace(.01,.99,100);y=(p>.8).astype(int)
    c=ProbabilityCalibrator("isotonic").fit(p,y).predict(p)
    assert np.all((c>=0)&(c<=1))

def test_calibration_report_keeps_raw_and_calibrated():
    y=np.array([0,0,1,1]);p=np.array([.1,.2,.7,.8])
    r=calibration_report(y,p,p)
    assert r["raw_brier"]==r["calibrated_brier"]
