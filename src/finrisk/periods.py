from __future__ import annotations

import numpy as np
import pandas as pd

INSTANT_FEATURES = {"assets", "liabilities", "equity", "current_assets", "current_liabilities", "cash"}
DURATION_FEATURES = {"revenue", "net_income", "operating_income", "operating_cash_flow"}


def select_period_correct_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """Select facts whose duration semantics are valid for the filing.

    SEC FSDS qtrs is the number of fiscal quarters represented by a duration fact.
    10-Q filings may therefore contain 1-quarter discrete values or YTD durations
    (2 in Q2, 3 in Q3). We retain those valid duration facts here and convert YTD
    values to discrete quarters in build_period_matrix instead of dropping filings.
    """
    f = facts.copy()
    f = f[f["ddate"].eq(f["period"])]
    f["qtrs"] = pd.to_numeric(f["qtrs"], errors="coerce")
    base_form = f["form"].astype(str).str.replace("/A", "", regex=False)
    instant = f["feature"].isin(INSTANT_FEATURES) & f["qtrs"].eq(0)
    q_duration = f["feature"].isin(DURATION_FEATURES) & base_form.eq("10-Q") & f["qtrs"].isin([1, 2, 3])
    k_duration = f["feature"].isin(DURATION_FEATURES) & base_form.eq("10-K") & f["qtrs"].eq(4)
    return f.loc[instant | q_duration | k_duration].copy()


def _prefer_duration_fact(group: pd.DataFrame) -> pd.Series:
    """Prefer a discrete quarter when reported; otherwise retain the shortest YTD fact."""
    q = pd.to_numeric(group["qtrs"], errors="coerce")
    order = np.where(q.eq(0), 0, np.where(q.eq(1), 1, q))
    return group.assign(_order=order).sort_values(["_order", "tag"]).iloc[0]


def build_period_matrix(facts: pd.DataFrame) -> pd.DataFrame:
    selected = select_period_correct_facts(facts)
    if selected.empty:
        return pd.DataFrame()
    # A filing can expose multiple tags/durations for the same canonical feature.
    # Prefer instant/discrete-quarter facts. YTD is retained only when no discrete
    # value exists, preserving the filing for later explicit YTD differencing.
    selected = (
        selected.groupby(["adsh", "feature"], as_index=False, group_keys=False)
        .apply(_prefer_duration_fact, include_groups=False)
        .reset_index(drop=True)
    )
    index_cols = [
        c for c in ["adsh", "cik", "name", "sic", "form", "period", "filed", "fy", "fp", "afs"]
        if c in selected.columns
    ]
    wide = selected.pivot(index=index_cols, columns="feature", values="value").reset_index()
    wide.columns.name = None
    return wide.sort_values(["filed", "cik", "adsh"]).reset_index(drop=True)
