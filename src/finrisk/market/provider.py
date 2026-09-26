from __future__ import annotations
from typing import Protocol
import pandas as pd

class HistoricalMarketProvider(Protocol):
    """Provider must preserve delisted securities and return provenance per observation."""
    def security_candidates(self,names:list[str],start:pd.Timestamp,end:pd.Timestamp)->pd.DataFrame: ...
    def prices(self,security_id:str,start:pd.Timestamp,end:pd.Timestamp)->pd.DataFrame: ...

REQUIRED_SECURITY_COLUMNS={"security_id","security_name","valid_from","valid_to","source","source_identifier"}
REQUIRED_PRICE_COLUMNS={"security_id","date","close","volume","source","retrieved_at"}

def validate_security_candidates(df:pd.DataFrame)->None:
    missing=REQUIRED_SECURITY_COLUMNS-set(df.columns)
    if missing:raise ValueError(f"Missing historical-security columns: {sorted(missing)}")

def validate_prices(df:pd.DataFrame)->None:
    missing=REQUIRED_PRICE_COLUMNS-set(df.columns)
    if missing:raise ValueError(f"Missing market-price columns: {sorted(missing)}")
    if df.duplicated(["security_id","date"]).any():raise ValueError("Duplicate security/date observations")
