from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.resolution import normalize_entity_name

frame=pd.read_parquet("artifacts/source/strength/candidate_strength.parquet")
tied=frame[frame["top_score_tied"].fillna(False)].copy()
rows=[]
for _,r in tied.iterrows():
    ids=[str(x) for x in r["top_tied_security_ids"]]
    names=[normalize_entity_name(str(x)) for x in r["top_tied_security_names"]]
    isins=[str(x).strip().upper() for x in r["top_tied_isins"]]
    nonempty=[x for x in isins if x]
    unique_names=len(set(names))
    unique_isins=len(set(nonempty))
    rows.append({
        "cik":str(r["cik"]),
        "tied_count":len(ids),
        "unique_normalized_names":unique_names,
        "nonempty_isin_count":len(nonempty),
        "unique_nonempty_isins":unique_isins,
        "all_same_name":unique_names==1,
        "has_duplicate_isin":len(nonempty)>unique_isins,
        "all_nonempty_isins_same":bool(nonempty) and unique_isins==1,
        "same_name_distinct_isins":unique_names==1 and unique_isins>1,
        "different_names_shared_isin":unique_names>1 and len(nonempty)>unique_isins,
        "missing_isin_in_tie":len(nonempty)<len(ids),
    })
d=pd.DataFrame(rows)
report={
    "tied_issuers":int(len(d)),
    "all_same_normalized_name":int(d["all_same_name"].sum()),
    "all_nonempty_isins_same":int(d["all_nonempty_isins_same"].sum()),
    "same_name_distinct_isins":int(d["same_name_distinct_isins"].sum()),
    "different_names_shared_isin":int(d["different_names_shared_isin"].sum()),
    "ties_with_missing_isin":int(d["missing_isin_in_tie"].sum()),
    "ties_with_duplicate_isin":int(d["has_duplicate_isin"].sum()),
}
out=Path("artifacts/identity/entity-collapse-key-diagnostics");out.mkdir(parents=True,exist_ok=True)
d.to_parquet(out/"entity_collapse_key_diagnostics.parquet",index=False)
(out/"entity_collapse_key_diagnostics.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps(report,indent=2))
