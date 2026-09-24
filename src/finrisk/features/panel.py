from __future__ import annotations
import numpy as np
import pandas as pd


def add_financial_ratios(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    def ratio(numerator: str, denominator: str) -> pd.Series:
        if numerator not in out or denominator not in out:
            return pd.Series(np.nan, index=out.index)
        d = pd.to_numeric(out[denominator], errors="coerce").replace(0, np.nan)
        n = pd.to_numeric(out[numerator], errors="coerce")
        return n / d
    out["current_ratio"] = ratio("current_assets", "current_liabilities")
    out["liabilities_to_assets"] = ratio("liabilities", "assets")
    out["liabilities_to_equity"] = ratio("liabilities", "equity")
    out["roa"] = ratio("net_income", "assets")
    out["roe"] = ratio("net_income", "equity")
    out["operating_margin"] = ratio("operating_income", "revenue")
    out["net_margin"] = ratio("net_income", "revenue")
    out["operating_cf_margin"] = ratio("operating_cash_flow", "revenue")
    out["cash_to_liabilities"] = ratio("cash", "liabilities")
    return out
