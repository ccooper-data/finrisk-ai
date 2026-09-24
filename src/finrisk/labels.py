from __future__ import annotations

import pandas as pd


def normalize_distress_events(events: pd.DataFrame) -> pd.DataFrame:
    required = {"cik", "event_date", "event_type"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Missing event columns: {sorted(missing)}")
    out = events.copy()
    out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce")
    out = out.dropna(subset=["cik", "event_date", "event_type"])
    return out.sort_values(["cik", "event_date"]).drop_duplicates(["cik", "event_date", "event_type"])


def label_forward_distress(observations: pd.DataFrame, events: pd.DataFrame, horizon_days: int = 365, embargo_days: int = 0) -> pd.DataFrame:
    obs = observations.copy()
    obs["filed"] = pd.to_datetime(obs["filed"], errors="coerce")
    ev = normalize_distress_events(events)
    by_cik = {cik: grp["event_date"].sort_values().tolist() for cik, grp in ev.groupby("cik")}
    labels=[]; days_to_event=[]; event_dates=[]
    for row in obs.itertuples(index=False):
        filed=row.filed
        candidates=[d for d in by_cik.get(row.cik, []) if d > filed]
        next_event=candidates[0] if candidates else pd.NaT
        if pd.isna(next_event):
            delta=float("nan"); label=0
        else:
            delta=float((next_event-filed).days); label=int(embargo_days < delta <= horizon_days)
        labels.append(label); days_to_event.append(delta); event_dates.append(next_event)
    obs["distress_12m"]=labels
    obs["days_to_distress"]=days_to_event
    obs["next_distress_date"]=event_dates
    obs["label_horizon_days"]=horizon_days
    return obs
