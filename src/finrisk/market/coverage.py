from __future__ import annotations
import pandas as pd

def market_coverage_report(frame:pd.DataFrame,market_cols:list[str])->dict:
    x=frame.copy();x["filed"]=pd.to_datetime(x["filed"])
    available=x[market_cols].notna().any(axis=1);positive=x["distress_12m"].eq(1)
    report={"rows":int(len(x)),"market_rows":int(available.sum()),"row_coverage":float(available.mean()),
            "positives":int(positive.sum()),"market_positives":int((available&positive).sum()),
            "positive_coverage":float(available[positive].mean()) if positive.any() else 1.0}
    report["by_year"]={}
    for y,g in x.assign(_available=available).groupby(x["filed"].dt.year):
        pos=g["distress_12m"].eq(1)
        report["by_year"][str(y)]={"rows":int(len(g)),"row_coverage":float(g["_available"].mean()),
          "positives":int(pos.sum()),"positive_coverage":float(g.loc[pos,"_available"].mean()) if pos.any() else 1.0}
    return report
