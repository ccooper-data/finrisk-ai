from __future__ import annotations
import pandas as pd

def survivorship_gate(frame:pd.DataFrame,has_market_col:str="has_market_data",max_positive_drop:float=.05,max_row_drop:float=.25)->dict:
    total=len(frame);positives=frame["distress_12m"].eq(1)
    kept=frame[has_market_col].fillna(False)
    row_drop=1-float(kept.mean());positive_drop=1-float(kept[positives].mean()) if positives.any() else 0.
    passed=row_drop<=max_row_drop and positive_drop<=max_positive_drop
    evidence={"passed":passed,"row_drop_rate":row_drop,"positive_drop_rate":positive_drop,
              "max_row_drop":max_row_drop,"max_positive_drop":max_positive_drop}
    if not passed:raise ValueError(f"Survivorship gate failed: {evidence}")
    return evidence
