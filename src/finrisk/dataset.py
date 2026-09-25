from __future__ import annotations

from collections.abc import Iterable
import pandas as pd

TAG_MAP = {
    "Assets": "assets",
    "Liabilities": "liabilities",
    "StockholdersEquity": "equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "equity",
    "AssetsCurrent": "current_assets",
    "LiabilitiesCurrent": "current_liabilities",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue",
    "SalesRevenueNet": "revenue",
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "OperatingIncomeLoss": "operating_income",
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
}

SUB_COLUMNS = ["adsh", "cik", "name", "sic", "form", "period", "filed", "fy", "fp", "afs"]
NUM_COLUMNS = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "value", "coreg", "segments"]


def eligible_submissions(sub: pd.DataFrame) -> pd.DataFrame:
    out = sub.copy()
    out = out[out["form"].isin(["10-K", "10-Q", "10-K/A", "10-Q/A"])]
    filed_numeric = pd.to_numeric(out["filed"], errors="coerce").astype("Int64")
    period_numeric = pd.to_numeric(out["period"], errors="coerce").astype("Int64")
    out["filed"] = pd.to_datetime(
        filed_numeric.astype("string"), format="%Y%m%d", errors="coerce"
    )
    out["period"] = pd.to_datetime(
        period_numeric.astype("string"), format="%Y%m%d", errors="coerce"
    )
    out = out.dropna(subset=["adsh", "cik", "filed", "period"])
    return out


def canonical_numeric_facts(num: pd.DataFrame, submissions: pd.DataFrame) -> pd.DataFrame:
    facts = num[num["tag"].isin(TAG_MAP)].copy()
    facts = facts[facts["uom"].eq("USD")]
    if "coreg" in facts.columns:
        facts = facts[facts["coreg"].isna() | facts["coreg"].eq("")]
    facts["feature"] = facts["tag"].map(TAG_MAP)
    facts["ddate"] = pd.to_datetime(facts["ddate"].astype("string"), format="%Y%m%d", errors="coerce")
    meta_cols = [c for c in SUB_COLUMNS if c in submissions.columns]
    return facts.merge(submissions[meta_cols], on="adsh", how="inner", validate="many_to_one")


def build_submission_matrix(facts: pd.DataFrame) -> pd.DataFrame:
    from finrisk.periods import build_period_matrix
    return build_period_matrix(facts)


def enforce_knowledge_cutoff(frame: pd.DataFrame, as_of: str | pd.Timestamp) -> pd.DataFrame:
    cutoff = pd.Timestamp(as_of)
    filed = pd.to_datetime(frame["filed"])
    return frame.loc[filed <= cutoff].copy()


def concatenate_quarters(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    frames = list(frames)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
