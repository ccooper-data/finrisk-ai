from __future__ import annotations
import json,os
import pandas as pd
from finrisk.market.eodhd import EODHDProbeAdapter

u=EODHDProbeAdapter(os.environ["EODHD_API_TOKEN"]).fetch_security_master()
u["has_isin"]=u["isin"].notna() & u["isin"].astype(str).str.strip().ne("")
g=u.groupby("is_delisted",dropna=False)["has_isin"].agg(["count","sum"]).reset_index()
report={
    "rows":int(len(u)),
    "overall_with_isin":int(u["has_isin"].sum()),
    "overall_without_isin":int((~u["has_isin"]).sum()),
    "by_delisted_status":[
        {"is_delisted":bool(r["is_delisted"]),"rows":int(r["count"]),"with_isin":int(r["sum"]),
         "without_isin":int(r["count"]-r["sum"]),"coverage_rate":float(r["sum"]/r["count"]) if r["count"] else None}
        for _,r in g.iterrows()
    ],
    "validity_is_provider_evidence":False,
    "adapter_validity_note":"fetch_security_master currently assigns 1900-01-01 to 2100-01-01 constants; these are placeholders, not observed listing intervals",
}
print(json.dumps(report,indent=2))
pd.DataFrame(report["by_delisted_status"]).to_csv("isin_coverage_by_delisted_status.csv",index=False)
