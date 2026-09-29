"""Right-censoring: a knowable label is not the same as a complete window.

label_forward_distress marks a positive inside an incomplete window as knowable,
which is correct -- the event was observed. But such rows are not a sample of that
period: their non-event counterparts are still censored. Selecting on knowability
alone leaves the recent edge of the cohort ~100% positive.
"""
from __future__ import annotations
import pandas as pd
import pytest
from finrisk.labels import (
    censoring_inventory, label_forward_distress, load_modelling_cohort,
    select_modelling_observations,
)
from finrisk.modeling.baseline import TemporalSplit

CUTOFF = pd.Timestamp("2026-06-30")
HORIZON = 365


def _cohort(issuers=40, quarters=24, distressed=8):
    obs, events = [], []
    for i in range(issuers):
        cik = str(1000 + i)
        for q in range(quarters):
            obs.append({"cik": cik, "adsh": f"{cik}-{q}",
                        "filed": pd.Timestamp("2020-09-30") + pd.DateOffset(months=3 * q)})
        if i < distressed:
            events.append({"cik": cik, "event_type": "sec_8k_item_1_03",
                           "event_date": pd.Timestamp("2025-03-15") + pd.DateOffset(months=2 * i)})
    return label_forward_distress(pd.DataFrame(obs), pd.DataFrame(events),
                                  horizon_days=HORIZON, observed_through=CUTOFF)


LABELLED = _cohort()


def test_knowability_and_window_completeness_are_separate_columns():
    assert {"label_mature", "label_window_complete"} <= set(LABELLED.columns)
    censored = ~LABELLED["label_window_complete"]
    # knowable-but-censored rows exist, and they are exactly the positives
    knowable_censored = LABELLED.loc[censored & LABELLED["distress_12m"].notna(), "distress_12m"]
    assert len(knowable_censored) > 0
    assert set(knowable_censored.unique()) == {1}


def test_selecting_on_knowability_alone_makes_the_censored_tail_all_positive():
    """The defect this guards. Selecting notna() only is NOT a valid cohort."""
    censored = ~LABELLED["label_window_complete"]
    naive = LABELLED.loc[censored & LABELLED["distress_12m"].notna(), "distress_12m"]
    assert naive.mean() == 1.0


def test_selection_requires_a_complete_window():
    selected = select_modelling_observations(LABELLED)
    window_end = pd.to_datetime(selected["filed"]) + pd.Timedelta(days=HORIZON)
    assert (window_end <= CUTOFF).all()
    assert selected["distress_12m"].notna().all()
    assert 0.0 < selected["distress_12m"].mean() < 0.5


def test_selection_returns_a_plain_integer_label():
    selected = select_modelling_observations(LABELLED)
    assert selected["distress_12m"].dtype.kind == "i"
    selected["distress_12m"].astype(int)   # must not raise


def test_raw_cohort_would_crash_every_model_runner():
    """Why the loader exists: .astype(int) on the raw frame raises."""
    with pytest.raises(ValueError, match="cannot convert NA to integer"):
        LABELLED["distress_12m"].astype(int)


def test_loader_is_the_single_entry_point(tmp_path):
    path = tmp_path / "cohort.parquet"
    LABELLED.to_parquet(path)
    loaded = load_modelling_cohort(path)
    pd.testing.assert_frame_equal(loaded, select_modelling_observations(LABELLED),
                                 check_dtype=False)


def test_every_model_runner_uses_the_loader():
    import inspect
    from finrisk.modeling import (
        baseline, boosted_tree, macro_ablation, pytorch_gru, pytorch_mlp,
        seed_sweep, tensorflow_gru, tensorflow_mlp,
    )
    for module in (baseline, boosted_tree, macro_ablation, pytorch_gru,
                   pytorch_mlp, seed_sweep, tensorflow_gru, tensorflow_mlp):
        source = inspect.getsource(module)
        assert "load_modelling_cohort(cohort_path)" in source, module.__name__


def test_inventory_answers_the_cohort_comparison_directly():
    report = censoring_inventory(LABELLED, split=TemporalSplit())
    assert report["rows_total"] == len(LABELLED)
    assert report["rows_censored"] > 0
    assert report["censored_knowable_positives"] == report["censored_with_knowable_label"]
    assert report["retained_rows"] + report["rows_censored"] == report["rows_total"]
    assert report["observed_through"] == "2026-06-30"
    assert report["retained_prevalence"] == pytest.approx(
        select_modelling_observations(LABELLED)["distress_12m"].mean())


def test_inventory_shows_censoring_confined_to_the_recent_period():
    report = censoring_inventory(LABELLED, split=TemporalSplit())
    per_split = report["per_split"]
    assert per_split["train"]["rows_dropped"] == 0
    assert per_split["validation"]["rows_dropped"] == 0
    assert per_split["test"]["rows_dropped"] == report["rows_censored"]
    assert report["censoring_confined_to_test"] is True


def test_no_cutoff_means_nothing_is_censored():
    open_ended = label_forward_distress(
        LABELLED[["cik", "adsh", "filed"]].copy(),
        pd.DataFrame([{"cik": "1000", "event_date": pd.Timestamp("2025-03-15"),
                       "event_type": "sec_8k_item_1_03"}]),
        horizon_days=HORIZON, observed_through=None)
    assert open_ended["label_window_complete"].all()
    assert open_ended["distress_12m"].notna().all()
