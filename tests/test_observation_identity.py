from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from finrisk.modeling import observation_identity as oid
from finrisk.modeling.sequences import SequenceConfig, build_sequence_arrays


def _frame(rows):
    return pd.DataFrame(rows)


def test_cik_keeps_leading_zeros_as_a_canonical_string():
    ids = oid.identifiers_from_frame(_frame([
        {"cik": "0000895648", "adsh": "a-1", "filed": "2010-05-01"},
        {"cik": 73887, "adsh": "a-2", "filed": "2010-05-02"},
    ]))
    assert list(ids["cik"]) == ["0000895648", "0000073887"]


def test_absent_event_linkage_is_recorded_not_omitted():
    ids = oid.identifiers_from_frame(_frame([
        {"cik": "1", "adsh": "a", "filed": "2020-01-01", "next_distress_date": "2020-06-01"},
        {"cik": "2", "adsh": "b", "filed": "2020-01-01", "next_distress_date": None},
    ]))
    assert ids["event_id"][0] == "0000000001:2020-06-01"
    assert ids["event_id"][1] == oid.UNAVAILABLE
    cov = oid.coverage(ids)
    assert cov["rows_with_linked_event"] == 1
    assert cov["unique_linked_events"] == 1
    assert cov["event_linkage"] == "from_next_distress_date"


def test_coverage_reports_unique_issuers_rather_than_assuming_event_counts():
    ids = oid.identifiers_from_frame(_frame([
        {"cik": "5", "adsh": "a", "filed": "2020-01-01"},
        {"cik": "5", "adsh": "b", "filed": "2020-04-01"},
        {"cik": "6", "adsh": "c", "filed": "2020-04-01"},
    ]))
    cov = oid.coverage(ids)
    assert cov["rows"] == 3 and cov["unique_ciks"] == 2
    assert cov["unique_observation_ids"] == 3
    assert cov["unique_linked_events"] == 0
    assert cov["event_linkage"] == oid.UNAVAILABLE


def test_length_agreement_alone_is_not_treated_as_alignment_proof():
    ids = oid.identifiers_from_frame(_frame([{"cik": "1", "adsh": "a", "filed": "2020-01-01"}]))
    oid.assert_aligned(ids, np.array([0.5]), "test")
    with pytest.raises(ValueError, match="1 identifiers for 2 probabilities"):
        oid.assert_aligned(ids, np.array([0.5, 0.5]), "test")


# --- Sequence-path alignment ---------------------------------------------------
#
# build_sequence_arrays groups by issuer, sorts by filing date and drops rows with
# insufficient history, so its output order does not match the input frame.
# Identifiers must therefore be emitted from inside that loop.

def _cohort(n_per_cik=6, ciks=("0000000011", "0000000022", "0000000033")):
    rows = []
    for cik in ciks:
        for i in range(n_per_cik):
            rows.append({
                "cik": cik, "adsh": f"{cik}-{i}",
                "filed": pd.Timestamp("2015-01-31") + pd.DateOffset(months=3 * i),
                "assets": 100.0 + i, "liabilities": 50.0 + i, "equity": 50.0,
                "current_assets": 40.0, "current_liabilities": 20.0, "cash": 10.0,
                "revenue": 30.0, "net_income": 2.0, "operating_income": 3.0,
                "operating_cash_flow": 4.0, "current_ratio": 2.0,
                "liabilities_to_assets": 0.5, "liabilities_to_equity": 1.0,
                "roa": 0.02, "roe": 0.04, "operating_margin": 0.1,
                "net_margin": 0.06, "cash_to_liabilities": 0.2,
                "distress_12m": 1 if (cik.endswith("22") and i == 5) else 0,
                "next_distress_date": pd.Timestamp("2016-06-30") if cik.endswith("22") else None,
            })
    return pd.DataFrame(rows)


def test_sequence_identifiers_match_each_sequence_endpoint():
    cohort = _cohort()
    config = SequenceConfig(lookback=4, min_history=2)
    _, labels, _, _, _, ids = build_sequence_arrays(cohort, config=config)
    oid.assert_aligned(ids, labels, "sequence")
    lookup = {f"{str(r.cik).zfill(10)}:{r.adsh}": r for r in cohort.itertuples()}
    for i, obs in enumerate(ids["observation_id"]):
        assert obs in lookup, obs
        assert int(labels[i]) == int(lookup[obs].distress_12m)
        assert ids["filed"][i] == pd.Timestamp(lookup[obs].filed).date().isoformat()


def test_sequence_identifiers_survive_shuffled_input_order():
    cohort = _cohort()
    config = SequenceConfig(lookback=4, min_history=2)
    _, labels_a, _, _, _, ids_a = build_sequence_arrays(cohort, config=config)
    shuffled = cohort.sample(frac=1.0, random_state=3).reset_index(drop=True)
    _, labels_b, _, _, _, ids_b = build_sequence_arrays(shuffled, config=config)
    pair_a = sorted(zip(ids_a["observation_id"], labels_a.tolist()))
    pair_b = sorted(zip(ids_b["observation_id"], labels_b.tolist()))
    assert pair_a == pair_b


def test_history_exclusions_drop_identifiers_with_their_rows():
    cohort = _cohort(n_per_cik=3)
    config = SequenceConfig(lookback=4, min_history=3)
    _, labels, _, _, meta, ids = build_sequence_arrays(cohort, config=config)
    # only the third filing of each issuer has three quarters of history
    assert len(labels) == 3
    assert sorted(i[-2:] for i in ids["adsh"]) == ["-2", "-2", "-2"]
    assert meta["identifier_coverage"]["unique_ciks"] == 3


def test_repeated_issuers_and_multiple_filings_keep_distinct_observation_ids():
    _, _, _, _, meta, ids = build_sequence_arrays(_cohort(), config=SequenceConfig(lookback=4, min_history=2))
    cov = meta["identifier_coverage"]
    assert cov["unique_ciks"] == 3
    assert cov["unique_observation_ids"] == cov["rows"]
    assert pd.Series(ids["cik"]).value_counts().min() > 1


def test_event_identifiers_are_not_model_features():
    from finrisk.modeling.sequences import SEQUENCE_FEATURES
    assert not (set(oid.IDENTIFIER_FIELDS) & set(SEQUENCE_FEATURES))
    sequences, _, _, _, meta, _ = build_sequence_arrays(_cohort(), config=SequenceConfig(lookback=4, min_history=2))
    assert sequences.shape[2] == len(meta["features"])
    assert all(f not in meta["features"] for f in oid.IDENTIFIER_FIELDS)
