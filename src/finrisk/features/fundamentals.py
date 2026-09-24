from __future__ import annotations
import pandas as pd
CONCEPTS={"assets":["Assets"],"liabilities":["Liabilities"],"equity":["StockholdersEquity","StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],"current_assets":["AssetsCurrent"],"current_liabilities":["LiabilitiesCurrent"],"cash":["CashAndCashEquivalentsAtCarryingValue","CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],"revenue":["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet"],"net_income":["NetIncomeLoss","ProfitLoss"],"operating_income":["OperatingIncomeLoss"],"operating_cash_flow":["NetCashProvidedByUsedInOperatingActivities"]}
def _facts_for(payload,tags):
    gaap=payload.get("facts",{}).get("us-gaap",{})
    for tag in tags:
        node=gaap.get(tag)
        if node and "USD" in node.get("units",{}):return node["units"]["USD"]
    return []
def point_in_time_fundamentals(payload,as_of):
    cutoff=pd.Timestamp(as_of);result={"cik":payload.get("cik"),"entity":payload.get("entityName"),"as_of":cutoff.date().isoformat()}
    for name,tags in CONCEPTS.items():
        eligible=[r for r in _facts_for(payload,tags) if r.get("filed") and pd.Timestamp(r["filed"])<=cutoff and r.get("form") in {"10-K","10-Q","10-K/A","10-Q/A"}]
        eligible.sort(key=lambda r:(r.get("filed",""),r.get("end","")));result[name]=eligible[-1]["val"] if eligible else None
    return result
def risk_features(f):
    def div(a,b):return None if a is None or b in (None,0) else a/b
    return {**f,"current_ratio":div(f.get("current_assets"),f.get("current_liabilities")),"debt_to_assets_proxy":div(f.get("liabilities"),f.get("assets")),"debt_to_equity_proxy":div(f.get("liabilities"),f.get("equity")),"roa":div(f.get("net_income"),f.get("assets")),"roe":div(f.get("net_income"),f.get("equity")),"operating_margin":div(f.get("operating_income"),f.get("revenue")),"net_margin":div(f.get("net_income"),f.get("revenue")),"operating_cf_margin":div(f.get("operating_cash_flow"),f.get("revenue")),"cash_to_liabilities":div(f.get("cash"),f.get("liabilities"))}
