import pandas as pd
from finrisk.labels import label_forward_distress

def test_immature_negative_is_censored():
    obs=pd.DataFrame({"cik":["1"],"filed":["2026-06-30"]})
    ev=pd.DataFrame(columns=["cik","event_date","event_type"])
    out=label_forward_distress(obs,ev,observed_through="2026-09-25")
    assert pd.isna(out.loc[0,"distress_12m"])
    assert not bool(out.loc[0,"label_mature"])

def test_mature_negative_remains_zero():
    obs=pd.DataFrame({"cik":["1"],"filed":["2024-01-01"]})
    ev=pd.DataFrame(columns=["cik","event_date","event_type"])
    out=label_forward_distress(obs,ev,observed_through="2026-09-25")
    assert out.loc[0,"distress_12m"]==0
    assert bool(out.loc[0,"label_mature"])

def test_observed_positive_is_known_before_window_fully_matures():
    obs=pd.DataFrame({"cik":["1"],"filed":["2026-01-01"]})
    ev=pd.DataFrame({"cik":["1"],"event_date":["2026-06-01"],"event_type":["sec_8k_item_1_03"]})
    out=label_forward_distress(obs,ev,observed_through="2026-09-25")
    assert out.loc[0,"distress_12m"]==1
    assert bool(out.loc[0,"label_mature"])

def test_event_after_horizon_does_not_make_immature_negative_known():
    obs=pd.DataFrame({"cik":["1"],"filed":["2026-01-01"]})
    ev=pd.DataFrame({"cik":["1"],"event_date":["2027-06-01"],"event_type":["sec_8k_item_1_03"]})
    out=label_forward_distress(obs,ev,observed_through="2026-09-25")
    assert pd.isna(out.loc[0,"distress_12m"])
    assert not bool(out.loc[0,"label_mature"])

def test_snapshot_date_comes_from_source_file_mtime(tmp_path):
    import os
    from finrisk.cohort_builder import submissions_snapshot_date
    p=tmp_path/"submissions.zip";p.write_bytes(b"x")
    ts=pd.Timestamp("2026-09-25T12:00:00Z").timestamp()
    os.utime(p,(ts,ts))
    assert submissions_snapshot_date(p)==pd.Timestamp("2026-09-25")
