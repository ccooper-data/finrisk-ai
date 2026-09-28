from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

d=pd.read_parquet("artifacts/source/identity/historical_identity_master.parquet")
hard=d[(d["distress_observations"]>0)&(~d["has_current_ticker"])].copy()
hard=hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(100)
hard["first_year"]=pd.to_datetime(hard["first_filing"]).dt.year
hard["last_year"]=pd.to_datetime(hard["last_filing"]).dt.year
report={
 "hard_cases":int(len(hard)),
 "first_filing_year_min":int(hard["first_year"].min()),
 "first_filing_year_max":int(hard["first_year"].max()),
 "last_filing_year_min":int(hard["last_year"].min()),
 "last_filing_year_max":int(hard["last_year"].max()),
 "first_filing_before_1996":int((hard["first_year"]<1996).sum()),
 "first_filing_1996_2019":int(hard["first_year"].between(1996,2019).sum()),
 "first_filing_2020_plus":int((hard["first_year"]>=2020).sum()),
 "last_filing_before_1996":int((hard["last_year"]<1996).sum()),
 "last_filing_1996_2019":int(hard["last_year"].between(1996,2019).sum()),
 "last_filing_2020_plus":int((hard["last_year"]>=2020).sum()),
 "by_first_filing_decade":{str((int(y)//10)*10):int(v) for y,v in hard["first_year"].value_counts().groupby(lambda y:(int(y)//10)*10).sum().sort_index().items()},
}
out=Path("artifacts/identity/hardcase-era-profile");out.mkdir(parents=True,exist_ok=True)
(out/"hardcase_era_profile.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps(report,indent=2))
