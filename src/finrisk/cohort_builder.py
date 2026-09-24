from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import zipfile
import httpx
import pandas as pd
from finrisk.dataset import eligible_submissions, canonical_numeric_facts, build_submission_matrix
from finrisk.features.panel import add_financial_ratios
from finrisk.ingestion.sec_fsds import Quarter, SecFinancialStatementDatasetClient, read_table
from finrisk.labels import label_forward_distress

SEC_SUBMISSIONS_BULK = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"

@dataclass(frozen=True)
class CohortBuildConfig:
    start_year:int=2009
    end_year:int=2026
    end_quarter:int=2
    forms:tuple[str,...]=("10-K","10-Q")
    horizon_days:int=365

def quarters(config):
    out=[]
    for year in range(config.start_year,config.end_year+1):
        last=config.end_quarter if year==config.end_year else 4
        for q in range(1,last+1):out.append(Quarter(year,q))
    return out

def download_submissions_bulk(user_agent:str,cache_dir:Path)->Path:
    if "@" not in user_agent:raise ValueError("SEC User-Agent must contain a contact email")
    cache_dir.mkdir(parents=True,exist_ok=True);path=cache_dir/"submissions.zip"
    if path.exists() and path.stat().st_size>0:return path
    headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"}
    with httpx.stream("GET",SEC_SUBMISSIONS_BULK,headers=headers,timeout=180) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_bytes():f.write(chunk)
    return path

def bankruptcy_events_from_submissions_archive(path:Path)->pd.DataFrame:
    rows=[]
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".json") or not name.startswith("CIK"):continue
            payload=json.loads(zf.read(name));cik=str(payload.get("cik",""))
            recent=(payload.get("filings") or {}).get("recent") or {}
            forms=recent.get("form",[]);dates=recent.get("filingDate",[])
            items=recent.get("items",[]);accessions=recent.get("accessionNumber",[])
            for i in range(min(len(forms),len(dates))):
                item=str(items[i]) if i<len(items) else ""
                if str(forms[i]).startswith("8-K") and "1.03" in {x.strip() for x in item.split(",")}:
                    rows.append({"cik":cik,"event_date":dates[i],"event_type":"sec_8k_item_1_03",
                                 "event_accession":accessions[i] if i<len(accessions) else None})
    return pd.DataFrame(rows,columns=["cik","event_date","event_type","event_accession"])

def build_sec_fundamentals(config,user_agent,cache_dir):
    client=SecFinancialStatementDatasetClient(user_agent);panels=[]
    for quarter in quarters(config):
        archive=client.download(quarter,cache_dir/"fsds")
        sub=eligible_submissions(read_table(archive,"sub"))
        sub=sub[sub["form"].isin(config.forms)].copy()
        if sub.empty:continue
        num=read_table(archive,"num");num=num[num["adsh"].isin(set(sub["adsh"]))].copy()
        panels.append(build_submission_matrix(canonical_numeric_facts(num,sub)))
    if not panels:return pd.DataFrame()
    out=pd.concat(panels,ignore_index=True)
    out=out.sort_values(["cik","filed","adsh"]).drop_duplicates(["adsh"],keep="last")
    return add_financial_ratios(out)

def build_labeled_sec_cohort(config,user_agent,cache_dir):
    fundamentals=build_sec_fundamentals(config,user_agent,cache_dir)
    events=bankruptcy_events_from_submissions_archive(download_submissions_bulk(user_agent,cache_dir))
    labeled=label_forward_distress(fundamentals,events,horizon_days=config.horizon_days)
    labeled["label_window_end"]=pd.to_datetime(labeled["filed"])+pd.to_timedelta(config.horizon_days,unit="D")
    return labeled,events

def cohort_inventory(frame,events):
    filed=pd.to_datetime(frame["filed"],errors="coerce")
    feature_cols=[c for c in ("current_ratio","liabilities_to_assets","liabilities_to_equity","roa","roe",
        "operating_margin","net_margin","operating_cash_flow_margin","cash_to_liabilities") if c in frame]
    return {"rows":int(len(frame)),"companies":int(frame["cik"].nunique()),
        "start":str(filed.min().date()) if len(frame) else None,"end":str(filed.max().date()) if len(frame) else None,
        "distress_events":int(len(events)),"positive_observations":int(frame["distress_12m"].sum()) if "distress_12m" in frame else 0,
        "prevalence":float(frame["distress_12m"].mean()) if len(frame) and "distress_12m" in frame else None,
        "feature_coverage":{c:float(frame[c].notna().mean()) for c in feature_cols}}
