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

    labels=[]; days_to_event=[]; event_dates=[]; mature=[]; complete=[]
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
        window_complete = bool(observation_cutoff is None or window_end <= observation_cutoff)
        # A distress event seen inside an otherwise-incomplete window makes the
        # label KNOWABLE, but such rows are not a sample of that period: their
        # non-event counterparts are still censored. Keeping them and dropping the
        # rest would make the censored region ~100% positive. So knowability and
        # window completeness are recorded separately, and modelling selects on
        # completeness -- see select_modelling_observations.
        label_knowable = bool(
            window_complete
            or (not pd.isna(next_event) and embargo_days < delta <= horizon_days)
        )
        if not label_knowable:
            label = pd.NA
        labels.append(label); days_to_event.append(delta); event_dates.append(next_event)
        mature.append(label_knowable); complete.append(window_complete)

    obs=obs.drop(columns=["_cik_key"])
    obs["distress_12m"]=pd.array(labels,dtype="Int64")
    obs["label_mature"]=mature
    obs["label_window_complete"]=complete
    obs["label_observed_through"]=observation_cutoff
    obs["days_to_distress"]=days_to_event
    obs["next_distress_date"]=event_dates
    obs["label_horizon_days"]=horizon_days
    return obs


MODELLING_LABEL = "distress_12m"


def load_modelling_cohort(cohort_path) -> pd.DataFrame:
    """Read a cohort parquet and return only rows fit for modelling/evaluation.

    Every model runner goes through this so no runner can reach .astype(int) with
    a censored pd.NA label, and none can silently keep the pure-positive censored
    tail.
    """
    return select_modelling_observations(pd.read_parquet(cohort_path))


def select_modelling_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """The single supported way to get a modelling/evaluation frame from a cohort.

    Requires a COMPLETE outcome window, not merely a knowable label. Positives
    observed inside an incomplete window are excluded here: retaining them while
    their censored non-event counterparts are dropped would put a block of pure
    positives at the recent edge of the test split and corrupt prevalence, average
    precision and every calibration figure computed from it.

    Also returns a plain integer label, so callers never run .astype(int) against
    a nullable column holding pd.NA.
    """
    if MODELLING_LABEL not in frame.columns:
        raise ValueError(f"Cohort is missing {MODELLING_LABEL}")
    out = frame
    if "label_window_complete" in out.columns:
        out = out[out["label_window_complete"].fillna(False).astype(bool)]
    out = out[out[MODELLING_LABEL].notna()].copy()
    out[MODELLING_LABEL] = out[MODELLING_LABEL].astype("int64")
    return out.reset_index(drop=True)


def censoring_inventory(frame: pd.DataFrame, split=None) -> dict:
    """What the censoring correction removed, and from where.

    Written to answer the cohort comparison directly: how many observations are
    dropped, how many positives survive, and whether only the recent period moved.
    """
    filed = pd.to_datetime(frame["filed"], errors="coerce")
    complete = (frame["label_window_complete"].fillna(False).astype(bool)
                if "label_window_complete" in frame.columns
                else pd.Series(True, index=frame.index))
    knowable = frame[MODELLING_LABEL].notna()
    censored = ~complete
    report = {
        "rows_total": int(len(frame)),
        "rows_window_complete": int(complete.sum()),
        "rows_censored": int(censored.sum()),
        "censored_with_knowable_label": int((censored & knowable).sum()),
        "censored_knowable_positives": int(frame.loc[censored & knowable, MODELLING_LABEL].sum()),
        "retained_rows": int((complete & knowable).sum()),
        "retained_positives": int(frame.loc[complete & knowable, MODELLING_LABEL].sum()),
        "censored_first_filed": (str(filed[censored].min().date()) if censored.any() else None),
        "censored_last_filed": (str(filed[censored].max().date()) if censored.any() else None),
        "observed_through": (str(pd.Timestamp(frame["label_observed_through"].iloc[0]).date())
                             if "label_observed_through" in frame.columns and len(frame)
                             and not pd.isna(frame["label_observed_through"].iloc[0]) else None),
    }
    retained = frame.loc[complete & knowable, MODELLING_LABEL]
    report["retained_prevalence"] = float(retained.mean()) if len(retained) else None
    if split is not None:
        bounds = {"train": (None, pd.Timestamp(split.train_end)),
                  "validation": (pd.Timestamp(split.train_end), pd.Timestamp(split.validation_end)),
                  "test": (pd.Timestamp(split.validation_end), None)}
        per_split = {}
        for name, (lo, hi) in bounds.items():
            sel = pd.Series(True, index=frame.index)
            if lo is not None:
                sel &= filed > lo
            if hi is not None:
                sel &= filed <= hi
            kept = complete & knowable & sel
            per_split[name] = {
                "rows_before": int(sel.sum()),
                "rows_after": int(kept.sum()),
                "rows_dropped": int((sel & ~(complete & knowable)).sum()),
                "positives_after": int(frame.loc[kept, MODELLING_LABEL].sum()),
                "prevalence_after": (float(frame.loc[kept, MODELLING_LABEL].mean())
                                     if kept.any() else None),
            }
        report["per_split"] = per_split
        report["censoring_confined_to_test"] = bool(
            per_split["train"]["rows_dropped"] == 0
            and per_split["validation"]["rows_dropped"] == 0)
    return report
