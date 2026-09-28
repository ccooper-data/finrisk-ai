"""Prediction-aligned observation identities for evaluation metadata.

These identifiers exist so held-out evaluation can be resampled by issuer. They
are evaluation metadata and must never reach a model as features.

Alignment is the whole point, so it cannot be recovered by joining back to the
source frame afterwards. The tabular path predicts in partition row order, so
identifiers are taken from that same partition. The sequence path reorders,
groups and drops observations with insufficient history, so its identifiers must
be emitted from inside the construction loop alongside each sequence's
prediction endpoint -- see modeling.sequences.build_sequence_arrays.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

IDENTIFIER_FIELDS = ("cik", "adsh", "filed", "observation_id", "event_id")
UNAVAILABLE = "unavailable"


def _cik_key(value) -> str:
    """CIK as a zero-padded 10-digit string, so leading zeros survive the round trip."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return UNAVAILABLE
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(10) if digits else UNAVAILABLE


def _event_key(cik: str, next_distress_date) -> str:
    """Linked distress event, when the label evidence supplies one.

    The cohort carries `next_distress_date` rather than the event accession, so
    the event key is issuer + event date. Absence is recorded explicitly rather
    than silently omitted, because "no event" and "event not recorded" are
    different claims.
    """
    if next_distress_date is None or pd.isna(next_distress_date):
        return UNAVAILABLE
    return f"{cik}:{pd.Timestamp(next_distress_date).date().isoformat()}"


def identifiers_from_frame(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Identifiers for a partition whose rows align 1:1 with its predictions."""
    n = len(frame)
    cik = np.array([_cik_key(v) for v in frame.get("cik", pd.Series([None] * n))], dtype=object)
    adsh = np.array(
        [str(v) if v is not None and not pd.isna(v) else UNAVAILABLE
         for v in frame.get("adsh", pd.Series([None] * n))], dtype=object)
    filed_raw = pd.to_datetime(frame.get("filed", pd.Series([None] * n)), errors="coerce")
    filed = np.array([d.date().isoformat() if not pd.isna(d) else UNAVAILABLE for d in filed_raw],
                     dtype=object)
    events = frame.get("next_distress_date", pd.Series([None] * n))
    event_id = np.array([_event_key(c, e) for c, e in zip(cik, events)], dtype=object)
    return build(cik, adsh, filed, event_id)


def build(cik, adsh, filed, event_id) -> dict[str, np.ndarray]:
    cik = np.asarray(cik, dtype=object)
    adsh = np.asarray(adsh, dtype=object)
    filed = np.asarray(filed, dtype=object)
    event_id = np.asarray(event_id, dtype=object)
    observation_id = np.array([f"{c}:{a}" if a != UNAVAILABLE else f"{c}:{f}"
                               for c, a, f in zip(cik, adsh, filed)], dtype=object)
    out = {"cik": cik, "adsh": adsh, "filed": filed,
           "observation_id": observation_id, "event_id": event_id}
    assert_internally_consistent(out)
    return out


def assert_internally_consistent(identifiers: dict[str, np.ndarray]) -> None:
    missing = set(IDENTIFIER_FIELDS) - set(identifiers)
    if missing:
        raise ValueError(f"Identifiers missing fields: {sorted(missing)}")
    lengths = {field: len(identifiers[field]) for field in IDENTIFIER_FIELDS}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Identifier fields are ragged: {lengths}")


def assert_aligned(identifiers: dict[str, np.ndarray], probabilities, partition: str) -> None:
    """Length agreement is necessary but not sufficient; callers must also prove
    ordering, which the tests do by construction rather than by assertion."""
    assert_internally_consistent(identifiers)
    if len(identifiers["cik"]) != len(probabilities):
        raise ValueError(
            f"{partition}: {len(identifiers['cik'])} identifiers for "
            f"{len(probabilities)} probabilities")


def coverage(identifiers: dict[str, np.ndarray]) -> dict:
    """Report what the identifiers can and cannot support, without guessing."""
    assert_internally_consistent(identifiers)
    cik = identifiers["cik"]
    event_id = identifiers["event_id"]
    linked = event_id[event_id != UNAVAILABLE]
    return {
        "rows": int(len(cik)),
        "unique_ciks": int(pd.unique(cik).size),
        "ciks_unavailable": int(np.sum(cik == UNAVAILABLE)),
        "unique_observation_ids": int(pd.unique(identifiers["observation_id"]).size),
        "rows_with_linked_event": int(len(linked)),
        "unique_linked_events": int(pd.unique(linked).size),
        "event_linkage": "from_next_distress_date" if len(linked) else UNAVAILABLE,
    }
