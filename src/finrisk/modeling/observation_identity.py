"""Prediction-endpoint identities: evaluation metadata, never model features.

Tabular callers use the partition's prediction order. Sequence callers emit IDs
inside the sequence construction loop, alongside each prediction endpoint.
"""
from __future__ import annotations

from datetime import date
from numbers import Integral, Real
import re

import numpy as np
import pandas as pd

IDENTIFIER_FIELDS = ("cik", "adsh", "filed", "observation_id", "event_id")
UNAVAILABLE = "unavailable"


def _text(value) -> str:
    if value is None or pd.isna(value):
        return UNAVAILABLE
    return str(value).strip() or UNAVAILABLE


def _cik_key(value) -> str:
    """Accept ASCII digit strings, integers, or finite integral numeric floats.

    Missing, zero, negative, fractional, boolean, malformed, and overlength
    values become explicitly unavailable. Never strip punctuation to invent a
    plausible CIK. Decimal/scientific-notation strings are not supported.
    """
    if isinstance(value, (bool, np.bool_)):
        return UNAVAILABLE
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[0-9]{1,10}", text) is None:
            return UNAVAILABLE
        number = int(text)
    elif isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        if not np.isfinite(value) or value != int(value):
            return UNAVAILABLE
        number = int(value)
    else:
        return UNAVAILABLE
    return f"{number:010d}" if 0 < number <= 9999999999 else UNAVAILABLE


def _canonical_cik(value) -> bool:
    return isinstance(value, str) and value != UNAVAILABLE and _cik_key(value) == value


def _event_key(cik: str, next_distress_date) -> str:
    """Issuer/date key from supplied label metadata, not a verified event accession."""
    if not _canonical_cik(cik) or next_distress_date is None or pd.isna(next_distress_date):
        return UNAVAILABLE
    try:
        event_date = pd.Timestamp(next_distress_date)
        if pd.isna(event_date):
            return UNAVAILABLE
        return f"{cik}:{event_date.date().isoformat()}"
    except (TypeError, ValueError, OverflowError):
        return UNAVAILABLE


def _valid_event(cik, event_id) -> bool:
    if not _canonical_cik(cik) or not isinstance(event_id, str):
        return False
    if not event_id.startswith(cik + ":"):
        return False
    text = event_id[len(cik) + 1:]
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def identifiers_from_frame(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Preserve partition row order, marking unavailable metadata explicitly."""
    default = pd.Series([None] * len(frame), dtype=object)
    cik = np.array([_cik_key(v) for v in frame.get("cik", default)], dtype=object)
    adsh = np.array([_text(v) for v in frame.get("adsh", default)], dtype=object)
    dates = pd.to_datetime(frame.get("filed", default), errors="coerce")
    filed = np.array([d.date().isoformat() if not pd.isna(d) else UNAVAILABLE
                      for d in dates], dtype=object)
    events = frame.get("next_distress_date", default)
    event_id = np.array([_event_key(c, e) for c, e in zip(cik, events)], dtype=object)
    return build(cik, adsh, filed, event_id)


def build(cik, adsh, filed, event_id) -> dict[str, np.ndarray]:
    inputs = [np.asarray(v, dtype=object) for v in (cik, adsh, filed, event_id)]
    if any(v.ndim != 1 for v in inputs):
        raise ValueError("Identifier fields must be 1D arrays")
    if len({len(v) for v in inputs}) != 1:
        raise ValueError("Identifier fields are ragged")
    cik = np.array([_cik_key(v) for v in inputs[0]], dtype=object)
    adsh = np.array([_text(v) for v in inputs[1]], dtype=object)
    filed = np.array([_text(v) for v in inputs[2]], dtype=object)
    event_id = np.array([e if _valid_event(c, e) else UNAVAILABLE
                         for c, e in zip(cik, inputs[3])], dtype=object)
    observation_id = np.array([
        f"{c}:{a if a != UNAVAILABLE else f}"
        if c != UNAVAILABLE and (a != UNAVAILABLE or f != UNAVAILABLE) else UNAVAILABLE
        for c, a, f in zip(cik, adsh, filed)
    ], dtype=object)
    out = dict(zip(IDENTIFIER_FIELDS, (cik, adsh, filed, observation_id, event_id)))
    assert_internally_consistent(out)
    return out


def assert_internally_consistent(identifiers: dict[str, np.ndarray]) -> None:
    missing = set(IDENTIFIER_FIELDS) - set(identifiers)
    if missing:
        raise ValueError(f"Identifiers missing fields: {sorted(missing)}")
    if any(np.asarray(identifiers[f]).ndim != 1 for f in IDENTIFIER_FIELDS):
        raise ValueError("Identifier fields must be 1D arrays")
    lengths = {field: len(identifiers[field]) for field in IDENTIFIER_FIELDS}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Identifier fields are ragged: {lengths}")


def assert_aligned(identifiers: dict[str, np.ndarray], probabilities, partition: str) -> None:
    """Check structure/length; caller construction must establish row ordering."""
    assert_internally_consistent(identifiers)
    if len(identifiers["cik"]) != len(probabilities):
        raise ValueError(f"{partition}: {len(identifiers['cik'])} identifiers for "
                         f"{len(probabilities)} probabilities")


def coverage(identifiers: dict[str, np.ndarray]) -> dict:
    assert_internally_consistent(identifiers)
    cik = np.asarray(identifiers["cik"], dtype=object)
    valid = np.array([_canonical_cik(c) for c in cik], dtype=bool)
    unavailable = np.array([_text(c) == UNAVAILABLE for c in cik], dtype=bool)
    events = np.asarray(identifiers["event_id"], dtype=object)
    linked = events[np.array([_valid_event(c, e) for c, e in zip(cik, events)], dtype=bool)]
    observations = np.asarray(identifiers["observation_id"], dtype=object)
    observed = np.array([_text(o) != UNAVAILABLE for o in observations], dtype=bool) & valid
    return {
        "rows": int(len(cik)),
        "unique_ciks": int(pd.unique(cik[valid]).size),
        "ciks_unavailable": int(unavailable.sum()),
        "ciks_invalid": int((~valid & ~unavailable).sum()),
        "rows_with_valid_cik": int(valid.sum()),
        "unique_observation_ids": int(pd.unique(observations[observed]).size),
        "rows_with_linked_event": int(len(linked)),
        "unique_linked_events": int(pd.unique(linked).size),
        "event_linkage": "from_next_distress_date" if len(linked) else UNAVAILABLE,
    }


def cluster_bootstrap_readiness(test_identifiers: dict | None) -> dict:
    """Mechanical prerequisites only for a paired, test-set CIK bootstrap.

    Every test row needs a valid CIK; do not silently exclude missing rows.
    Two distinct clusters are a nondegeneracy minimum, not a claim of sufficient
    statistical information. Validation/event IDs are not required for this scope.
    """
    blockers = []
    cov = coverage(test_identifiers) if test_identifiers is not None else None
    if cov is None:
        blockers.append("test_identifiers_not_supplied")
    else:
        if cov["rows"] == 0:
            blockers.append("empty_test_population")
        if cov["ciks_unavailable"]:
            blockers.append("test_ciks_unavailable")
        if cov["ciks_invalid"]:
            blockers.append("test_ciks_invalid")
        if cov["unique_ciks"] < 2:
            blockers.append("fewer_than_two_distinct_test_ciks")
    return {
        "evaluation_partition": "test",
        "cluster_key": "cik",
        "scope": "conditional_on_fitted_model_and_calibrator",
        "identifiers_available": bool(cov and cov["rows"] > 0
                                      and cov["rows_with_valid_cik"] == cov["rows"]),
        "minimum_distinct_clusters": 2,
        "supports_cluster_bootstrap": not blockers,
        "blockers": blockers,
        "statistical_adequacy": "not_established",
        "upstream_alignment_verified": False,
    }
