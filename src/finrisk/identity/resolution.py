from __future__ import annotations
import re,unicodedata
import pandas as pd

LEGAL_SUFFIXES={"INC","INCORPORATED","CORP","CORPORATION","CO","COMPANY","LTD","LIMITED","LLC","PLC","LP","L P"}

def normalize_entity_name(value:str)->str:
    text=unicodedata.normalize("NFKD",str(value)).upper()
    text=re.sub(r"[^A-Z0-9 ]+"," ",text)
    tokens=[t for t in text.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)

def build_identity_master(cohort:pd.DataFrame,current_tickers:pd.DataFrame,historical_names:pd.DataFrame)->pd.DataFrame:
    c=cohort.copy();c["cik"]=c["cik"].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(10)
    base=(c.groupby("cik").agg(first_filing=("filed","min"),last_filing=("filed","max"),
          observations=("cik","size"),distress_observations=("distress_12m","sum")).reset_index())
    t=current_tickers.copy();t["cik"]=t["cik"].astype(str).str.zfill(10)
    ticker_roll=(t.groupby("cik").agg(current_tickers=("ticker",lambda s:sorted(set(map(str,s))))).reset_index())
    h=historical_names.copy();h["cik"]=h["cik"].astype(str).str.zfill(10)
    name_roll=(h.groupby("cik").agg(historical_names=("historical_name",lambda s:sorted(set(map(str,s))))).reset_index())
    out=base.merge(ticker_roll,on="cik",how="left").merge(name_roll,on="cik",how="left")
    out["has_current_ticker"]=out["current_tickers"].notna();out["has_historical_name"]=out["historical_names"].notna()
    out["identity_status"]=out.apply(lambda r:"current_ticker" if r.has_current_ticker else ("historical_name_only" if r.has_historical_name else "unresolved"),axis=1)
    return out

def candidate_score(sec_name:str,candidate_name:str)->float:
    a,b=normalize_entity_name(sec_name),normalize_entity_name(candidate_name)
    if not a or not b:return 0.0
    if a==b:return 1.0
    sa,sb=set(a.split()),set(b.split())
    return len(sa&sb)/len(sa|sb)

def classify_candidate(score:float,date_overlap:bool,identifier_evidence:bool=False)->str:
    if identifier_evidence and date_overlap:return "accepted_identifier"
    if score>=0.98 and date_overlap:return "review_exact_name"
    if score>=0.85 and date_overlap:return "review_candidate"
    return "rejected"
