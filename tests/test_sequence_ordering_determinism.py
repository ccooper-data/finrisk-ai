"""Point-in-time reconstruction: strictly future rows must not change the past.

The defect this guards was found by auditing a seed-42 run that failed to
reproduce. `build_sequence_arrays` re-sorted each issuer's rows by `filed` alone
with the default unstable sort, so same-day filings could be permuted -- and the
permutation depended on the whole frame. Removing only strictly later rows
changed the order of earlier same-day rows, and hence which rows fell inside a
past observation's lookback window.

No future-DATED value entered a history. The violated property is narrower and
still central: the feature tensor must be a function of {filed <= T} alone.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from finrisk.modeling.baseline import TemporalSplit
from finrisk.modeling.sequences import (
    GROUP_ORDER_KEYS, ORDER_KEYS, SequenceConfig, build_sequence_arrays,
)

# The imputer, scaler and the `observed` feature filter are fit on the TRAIN mask
# of whatever frame is passed, which is correct and intended. So the invariant
# these tests assert is necessarily conditional on a fixed training window:
# truncation and extension happen strictly after validation_end, leaving the
# train and validation partitions -- and therefore the fitted preprocessing --
# untouched. A test that truncated inside train would refit the scaler and fail
# for a legitimate reason; do not "fix" the source to satisfy that.
SPLIT = TemporalSplit()

FEATURES = {
    "assets": 100.0, "liabilities": 50.0, "equity": 50.0, "current_assets": 40.0,
    "current_liabilities": 20.0, "cash": 10.0, "revenue": 30.0, "net_income": 2.0,
    "operating_income": 3.0, "operating_cash_flow": 4.0, "current_ratio": 2.0,
    "liabilities_to_assets": 0.5, "liabilities_to_equity": 1.0, "roa": 0.02,
    "roe": 0.04, "operating_margin": 0.1, "net_margin": 0.06, "cash_to_liabilities": 0.2,
}


def _cohort(issuers=4, dates=40, per_date=2, seed=0, start="2015-01-31"):
    """Multiple filings per issuer per date, so same-day ties actually exist.

    Spans train, validation and test so rows can be added or removed strictly
    after validation_end without disturbing the fitted preprocessing.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for issuer in range(issuers):
        cik = str(11 * (issuer + 1))
        for d in range(dates):
            filed = pd.Timestamp(start) + pd.DateOffset(months=3 * d)
            for k in range(per_date):
                rows.append({
                    "cik": cik, "filed": filed,
                    "adsh": f"{cik}-{d:02d}-{k}",
                    **{f: v * (1.0 + 0.05 * d + 0.01 * k + 0.001 * rng.random())
                       for f, v in FEATURES.items()},
                    "distress_12m": 1 if (issuer == 1 and d == dates - 1) else 0,
                    "next_distress_date": None,
                })
    return pd.DataFrame(rows)


def _endpoints(frame, config):
    sequences, labels, _, lengths, _, ids = build_sequence_arrays(frame, split=SPLIT, config=config)
    return {obs: (sequences[i], int(labels[i]), int(lengths[i]))
            for i, obs in enumerate(ids["observation_id"])}


CONFIG = SequenceConfig(lookback=4, min_history=2)


def test_order_keys_are_total():
    assert ORDER_KEYS == ["cik", "filed", "adsh"]
    assert GROUP_ORDER_KEYS == ["filed", "adsh"]


def test_removing_strictly_future_rows_changes_neither_endpoints_nor_histories():
    full = _cohort()
    # strictly after validation_end, so train/validation preprocessing is identical
    cutoff = pd.Timestamp(SPLIT.validation_end) + pd.DateOffset(years=1)
    past = full[full["filed"] <= cutoff].copy()
    assert (full["filed"] > cutoff).any(), "fixture must contain strictly later rows"

    full_endpoints = _endpoints(full, CONFIG)
    past_endpoints = _endpoints(past, CONFIG)
    assert past_endpoints, "truncated cohort produced no sequences"

    for obs, (seq, label, length) in past_endpoints.items():
        assert obs in full_endpoints, f"{obs} vanished when future rows were added"
        full_seq, full_label, full_length = full_endpoints[obs]
        # The history itself, not just the endpoint identity.
        np.testing.assert_array_equal(seq, full_seq)
        assert (label, length) == (full_label, full_length)


def test_adding_strictly_future_rows_changes_neither_endpoints_nor_histories():
    full = _cohort()
    cutoff = pd.Timestamp(SPLIT.validation_end) + pd.DateOffset(years=1)
    past = full[full["filed"] <= cutoff].copy()
    extended = full.copy()
    assert len(extended) > len(past)
    past_endpoints = _endpoints(past, CONFIG)
    extended_endpoints = _endpoints(extended, CONFIG)
    assert past_endpoints
    for obs, (seq, label, length) in past_endpoints.items():
        assert obs in extended_endpoints
        np.testing.assert_array_equal(seq, extended_endpoints[obs][0])
        assert (label, length) == extended_endpoints[obs][1:]


def test_input_row_order_does_not_change_any_history():
    cohort = _cohort()
    a = _endpoints(cohort, CONFIG)
    b = _endpoints(cohort.sample(frac=1.0, random_state=7).reset_index(drop=True), CONFIG)
    assert set(a) == set(b)
    for obs in a:
        np.testing.assert_array_equal(a[obs][0], b[obs][0])
        assert a[obs][1:] == b[obs][1:]


def test_repeated_builds_are_bitwise_identical():
    cohort = _cohort()
    a, b = _endpoints(cohort, CONFIG), _endpoints(cohort, CONFIG)
    for obs in a:
        np.testing.assert_array_equal(a[obs][0], b[obs][0])


def test_same_day_filings_are_ordered_by_accession_not_by_sort_luck():
    cohort = _cohort(issuers=1, dates=3, per_date=3)
    _, _, _, _, _, ids = build_sequence_arrays(cohort, config=SequenceConfig(lookback=4, min_history=1))
    assert list(ids["adsh"]) == sorted(ids["adsh"])


def test_the_unstable_partial_sort_would_have_failed_this_regression():
    """Pins the mechanism: sorting on `filed` alone, unstable, reorders earlier
    same-day rows when only strictly later rows are removed."""
    def group_order(frame, keys, kind):
        out = frame.sort_values(ORDER_KEYS, kind="stable").copy()
        out["_row"] = np.arange(len(out))
        ordered = {}
        for cik, g in out.groupby("cik", sort=False):
            g = g.sort_values(keys, kind=kind)
            ordered[cik] = list(out.loc[g["_row"].to_numpy(), "adsh"])
        return ordered

    full = _cohort(issuers=1, dates=12, per_date=2)
    truncated = full.iloc[:-4].copy()          # strictly later rows only
    broken_full = group_order(full, "filed", "quicksort")["11"]
    broken_trunc = group_order(truncated, "filed", "quicksort")["11"]
    assert broken_full[:len(broken_trunc)] != broken_trunc

    fixed_full = group_order(full, GROUP_ORDER_KEYS, "stable")["11"]
    fixed_trunc = group_order(truncated, GROUP_ORDER_KEYS, "stable")["11"]
    assert fixed_full[:len(fixed_trunc)] == fixed_trunc


def test_runs_record_enough_environment_to_attribute_future_drift():
    from finrisk.modeling.run_environment import SEQUENCE_PREPROCESSING_VERSION, run_environment
    env = run_environment(sequence_preprocessing=True)
    for field in ("python", "platform", "numpy", "pandas", "scikit_learn", "torch", "tensorflow"):
        assert field in env, field
    assert env["sequence_preprocessing_version"] == SEQUENCE_PREPROCESSING_VERSION
    # torch may be absent locally; availability is recorded either way.
    assert "available" in env["torch"]
    assert "sequence_preprocessing_version" not in run_environment()
