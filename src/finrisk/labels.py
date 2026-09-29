from __future__ import annotations

import pandas as pd


def normalize_cik(value) -> str:
    """Canonical SEC CIK key: digits only, no leading zeros."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits.lstrip("0") or ("0" if digits else "")


def normalize_distress_events(events: pd.DataFrame) -> pd.DataFrame:
    required = {"cik", "event_date", "event_type"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Missing event columns: {sorted(missing)}")
    out = events.copy()
    out["cik"] = out["cik"].map(normalize_cik)
    out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce")
    out = out.dropna(subset=["event_date", "event_type"])
    out = out[out["cik"].ne("")]
    return out.sort_values(["cik", "event_date"]).drop_duplicates(
        ["cik", "event_date", "event_type"]
    )


def label_forward_distress(
    observations: pd.DataFrame,
    events: pd.DataFrame,
    horizon_days: int = 365,
    embargo_days: int = 0,
    observed_through: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    obs = observations.copy()
    obs["filed"] = pd.to_datetime(obs["filed"], errors="coerce")
    obs["_cik_key"] = obs["cik"].map(normalize_cik)
    ev = normalize_distress_events(events)
    observation_cutoff = pd.Timestamp(observed_through) if observed_through is not None else None
    if observation_cutoff is not None and pd.isna(observation_cutoff):
        raise ValueError("observed_through must be a valid date")
    by_cik = {
        cik: grp["event_date"].sort_values().tolist()
        for cik, grp in ev.groupby("cik")
    }

    labels=[]; days_to_event=[]; event_dates=[]; mature=[]
    for row in obs.itertuples(index=False):
        filed=row.filed
        cik_key=getattr(row, "_cik_key", None)
        # itertuples renames leading-underscore columns, so derive from original CIK.
        if cik_key is None:
            cik_key=normalize_cik(row.cik)
        candidates=[d for d in by_cik.get(cik_key, []) if d > filed]
        next_event=candidates[0] if candidates else pd.NaT
        if pd.isna(next_event):
            delta=float("nan"); label=0
        else:
            delta=float((next_event-filed).days)
            label=int(embargo_days < delta <= horizon_days)
        window_end = filed + pd.Timedelta(days=horizon_days)
        is_mature = bool(
            (not pd.isna(next_event) and embargo_days < delta <= horizon_days)
            or observation_cutoff is None
            or window_end <= observation_cutoff
        )
        if not is_mature:
            label = pd.NA
        labels.append(label); days_to_event.append(delta); event_dates.append(next_event); mature.append(is_mature)

    obs=obs.drop(columns=["_cik_key"])
    obs["distress_12m"]=pd.array(labels,dtype="Int64")
    obs["label_mature"]=mature
    obs["label_observed_through"]=observation_cutoff
    obs["days_to_distress"]=days_to_event
    obs["next_distress_date"]=event_dates
    obs["label_horizon_days"]=horizon_days
    return obs
