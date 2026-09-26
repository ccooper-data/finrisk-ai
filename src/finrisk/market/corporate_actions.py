from __future__ import annotations
import pandas as pd

REQUIRED_ACTIONS={"security_id","effective_date","action_type","source","source_identifier"}
ALLOWED_ACTIONS={"split","reverse_split","cash_dividend","stock_dividend","merger","spinoff","symbol_change"}

def validate_corporate_actions(df:pd.DataFrame)->None:
    missing=REQUIRED_ACTIONS-set(df.columns)
    if missing:raise ValueError(f"Missing corporate-action fields: {sorted(missing)}")
    bad=set(df["action_type"].dropna())-ALLOWED_ACTIONS
    if bad:raise ValueError(f"Unsupported corporate actions: {sorted(bad)}")
    if df.duplicated(["security_id","effective_date","action_type","source_identifier"]).any():
        raise ValueError("Duplicate corporate-action evidence")
