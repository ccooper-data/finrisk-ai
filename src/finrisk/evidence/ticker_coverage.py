from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def normalize_cik(s:pd.Series)->pd.Series:
    return s.astype(str).str.replace(r"\.0$","",regex=True).str.zfill(10)

def ticker_coverage(cohort_path:Path,map_path:Path,out_path:Path)->dict:
    cohort=pd.read_parquet(cohort_path);mapping=pd.read_parquet(map_path)
    cohort=cohort.copy();cohort["cik_norm"]=normalize_cik(cohort["cik"])
    mapping=mapping.copy();mapping["cik_norm"]=normalize_cik(mapping["cik"])
    known=set(mapping["cik_norm"]);cohort["has_current_ticker"]=cohort["cik_norm"].isin(known)
    cohort["filed"]=pd.to_datetime(cohort["filed"]);cohort["year"]=cohort["filed"].dt.year
    def stats(g):
        return {"rows":int(len(g)),"companies":int(g["cik_norm"].nunique()),
                "mapped_rows":int(g["has_current_ticker"].sum()),
                "row_coverage":float(g["has_current_ticker"].mean()),
                "positives":int(g["distress_12m"].sum()),
                "mapped_positives":int(g.loc[g["has_current_ticker"],"distress_12m"].sum())}
    report={"overall":stats(cohort),"by_year":{str(y):stats(g) for y,g in cohort.groupby("year")}}
    for name,mask in {
        "train":cohort["filed"]<=pd.Timestamp("2020-12-31"),
        "validation":(cohort["filed"]>pd.Timestamp("2020-12-31"))&(cohort["filed"]<=pd.Timestamp("2022-12-31")),
        "test":cohort["filed"]>pd.Timestamp("2022-12-31"),
    }.items():report.setdefault("splits",{})[name]=stats(cohort[mask])
    positives=cohort[cohort["distress_12m"].eq(1)]
    report["positive_row_coverage"]=float(positives["has_current_ticker"].mean())
    report["unmapped_positive_companies"]=int(positives.loc[~positives["has_current_ticker"],"cik_norm"].nunique())
    out_path.parent.mkdir(parents=True,exist_ok=True);out_path.write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
