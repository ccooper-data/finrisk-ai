from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.resolution import normalize_entity_name

def classify_row(row):
    ids=[str(x) for x in row["top_tied_security_ids"]]
    names=[normalize_entity_name(str(x)) for x in row["top_tied_security_names"]]
    isins=[str(x).strip().upper() for x in row["top_tied_isins"] if str(x).strip()]
    if len(set(ids)) < len(ids):
        return "duplicate_security_id"
    if isins and len(set(isins)) < len(isins):
        return "duplicate_isin"
    if len(set(names))==1:
        return "same_normalized_name_distinct_security"
    return "distinct_normalized_names"

frame=pd.read_parquet("artifacts/source/strength/candidate_strength.parquet")
tied=frame[frame["top_score_tied"].fillna(False)].copy()
tied["tie_composition"]=tied.apply(classify_row,axis=1)
report={
    "tied_issuers":int(len(tied)),
    "by_composition":{k:int(v) for k,v in tied["tie_composition"].value_counts().to_dict().items()},
    "tied_candidate_count_distribution":{str(k):int(v) for k,v in tied["top_tied_candidate_count"].value_counts().sort_index().to_dict().items()},
}
out=Path("artifacts/identity/tied-candidate-composition");out.mkdir(parents=True,exist_ok=True)
(out/"tied_candidate_composition.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps(report,indent=2))
