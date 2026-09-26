from __future__ import annotations
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss

class ProbabilityCalibrator:
    def __init__(self,method:str="isotonic"):
        if method not in {"isotonic","platt"}:raise ValueError("method must be isotonic or platt")
        self.method=method;self.model=None
    def fit(self,p,y):
        p=np.asarray(p,dtype=float);y=np.asarray(y,dtype=int)
        if self.method=="isotonic":
            self.model=IsotonicRegression(out_of_bounds="clip").fit(p,y)
        else:
            eps=1e-6;z=np.log(np.clip(p,eps,1-eps)/(1-np.clip(p,eps,1-eps))).reshape(-1,1)
            self.model=LogisticRegression().fit(z,y)
        return self
    def predict(self,p):
        p=np.asarray(p,dtype=float)
        if self.method=="isotonic":return np.asarray(self.model.predict(p))
        eps=1e-6;z=np.log(np.clip(p,eps,1-eps)/(1-np.clip(p,eps,1-eps))).reshape(-1,1)
        return self.model.predict_proba(z)[:,1]

def calibration_report(y,raw,calibrated):
    return {"raw_brier":float(brier_score_loss(y,raw)),"calibrated_brier":float(brier_score_loss(y,calibrated)),
            "raw_log_loss":float(log_loss(y,raw,labels=[0,1])),"calibrated_log_loss":float(log_loss(y,calibrated,labels=[0,1]))}
