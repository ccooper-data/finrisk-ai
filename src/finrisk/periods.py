from __future__ import annotations

import numpy as np
import pandas as pd

INSTANT_FEATURES = {"assets", "liabilities", "equity", "current_assets", "current_liabilities", "cash"}
DURATION_FEATURES = {"revenue", "net_income", "operating_income", "operating_cash_flow"}


def select_period_correct_facts(facts: pd.DataFrame) -> pd.DataFrame:
    f = facts.copy()
    f = f[f["ddate"].eq(f["period"])]
    f["qtrs"] = pd.to_numeric(f["qtrs"], errors="coerce")
    base_form = f["form"].astype(str).str.replace("/A", "", regex=False)
    desired = np.where(
        f["feature"].isin(INSTANT_FEATURES),
        0,
        np.where(base_form.eq("10-Q"), 1, np.where(base_form.eq("10-K"), 4, np.nan)),
    )
    f["desired_qtrs"] = desired
    return f.loc[f["qtrs"].eq(f["desired_qtrs"])].copy()


def build_period_matrix(facts: pd.DataFrame) -> pd.DataFrame:
    selected = select_period_correct_facts(facts)
    selected = selected.sort_values(["adsh", "feature", "tag"]).drop_duplicates(
        ["adsh", "feature"], keep="last"
    )
    index_cols = [
        c for c in ["adsh", "cik", "name", "sic", "form", "period", "filed", "fy", "fp", "afs"]
        if c in selected.columns
    ]
    wide = selected.pivot(index=index_cols, columns="feature", values="value").reset_index()
    wide.columns.name = None
    return wide.sort_values(["filed", "cik", "adsh"]).reset_index(drop=True)
