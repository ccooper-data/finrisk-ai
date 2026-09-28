from __future__ import annotations
import numpy as np
from sklearn.metrics import average_precision_score,brier_score_loss,log_loss,roc_auc_score
from finrisk.modeling.calibration import ProbabilityCalibrator

def probability_evidence(y_validation,p_validation,y_test,p_test,method:str="isotonic")->dict:
    yv=np.asarray(y_validation,dtype=int);pv=np.asarray(p_validation,dtype=float)
    yt=np.asarray(y_test,dtype=int);pt=np.asarray(p_test,dtype=float)
    calibrator=ProbabilityCalibrator(method).fit(pv,yv)
    calibrated=calibrator.predict(pt)
    prevalence=float(yt.mean())
    constant=np.full(len(yt),prevalence,dtype=float)
    return {
      "calibration_method":method,
      "fit_partition":"validation",
      "evaluation_partition":"test",
      "test_rows":int(len(yt)),
      "test_positives":int(yt.sum()),
      "test_prevalence":prevalence,
      "ranking":{
        "raw_roc_auc":float(roc_auc_score(yt,pt)),
        "calibrated_roc_auc":float(roc_auc_score(yt,calibrated)),
        "raw_pr_auc":float(average_precision_score(yt,pt)),
        "calibrated_pr_auc":float(average_precision_score(yt,calibrated)),
      },
      "probability_quality":{
        "raw_brier":float(brier_score_loss(yt,pt)),
        "calibrated_brier":float(brier_score_loss(yt,calibrated)),
        "base_rate_brier":float(brier_score_loss(yt,constant)),
        "raw_log_loss":float(log_loss(yt,pt,labels=[0,1])),
        "calibrated_log_loss":float(log_loss(yt,calibrated,labels=[0,1])),
      },
    }
