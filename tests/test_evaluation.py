import numpy as np
from finrisk.modeling.evaluation import rare_event_metrics

def test_alert_metrics_reward_ranked_positives():
    y=np.array([1,1]+[0]*998);good=np.linspace(1,0,1000);bad=good[::-1]
    assert rare_event_metrics(y,good)["pr_auc"]>rare_event_metrics(y,bad)["pr_auc"]
    assert rare_event_metrics(y,good)["alert_rates"]["0.005"]["lift"]>1

def test_metrics_report_prevalence():
    y=np.array([0,0,1,0]);p=np.array([.1,.2,.9,.3])
    assert rare_event_metrics(y,p)["prevalence"]==.25
