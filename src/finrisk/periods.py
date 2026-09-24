from __future__ import annotations

import pandas as pd

INSTANT_FEATURES = {"assets", "liabilities", "equity", "current_assets", "current_liabilities", "cash"}
DURATION_FEATURES = {"revenue", "net_income", "operating_income", "operating_cash_flow"}


def select_period_correct_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """Keep valid SEC duration semantics without discarding Q2/Q3 YTD filings."""
    f = facts.copy()
    f = f[f["ddate"].eq(f["period"])]
    f["qtrs"] = pd.to_numeric(f["qtrs"], errors="coerce")
    base_form = f["form"].astype(str).str.replace("/A", "", regex=False)
    instant = f["feature"].isin(INSTANT_FEATURES) & f["qtrs"].eq(0)
    q_duration = (
        f["feature"].isin(DURATION_FEATURES)
        & base_form.eq("10-Q")
        & f["qtrs"].isin([1, 2, 3])
    )
    k_duration = (
        f["feature"].isin(DURATION_FEATURES)
        & base_form.eq("10-K")
        & f["qtrs"].eq(4)
    )
    return f.loc[instant | q_duration | k_duration].copy()


def build_period_matrix(facts: pd.DataFrame) -> pd.DataFrame:
    selected = select_period_correct_facts(facts)
    if selected.empty:
        return pd.DataFrame()

    # Prefer instant/discrete-quarter facts. If no discrete duration is reported,
    # retain the shortest valid YTD duration so the filing is not silently lost.
    selected["_duration_rank"] = pd.to_numeric(selected["qtrs"], errors="coerce")
    selected = (
        selected.sort_values(["adsh", "feature", "_duration_rank", "tag"])
        .drop_duplicates(["adsh", "feature"], keep="first")
        .drop(columns=["_duration_rank"])
    )

    index_cols = [
        c for c in ["adsh", "cik", "name", "sic", "form", "period", "filed", "fy", "fp", "afs"]
        if c in selected.columns
    ]
    wide = selected.pivot(index=index_cols, columns="feature", values="value").reset_index()
    wide.columns.name = None
    return wide.sort_values(["filed", "cik", "adsh"]).reset_index(drop=True)
