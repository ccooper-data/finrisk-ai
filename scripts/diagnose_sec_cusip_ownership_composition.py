from __future__ import annotations
import json,re
from pathlib import Path
import pandas as pd

OWNERSHIP_TERMS=("our common stock","shares of our common stock","registrant","we have authorized","our shares")
THIRD_PARTY_TERMS=("collateral","portfolio","holdings","held by","investment","counterparty","acquired","acquisition","target company","borrower")

d=pd.read_parquet("artifacts/source/pilot/tier_a_identifier_evidence.parquet")
x=d[(d["identifier_type"].eq("CUSIP")) & d["common_equity_context"].fillna(False)].copy()
ctx=x["identifier_context"].fillna("").astype(str).str.lower()
x["ownership_language"]=ctx.map(lambda s:any(t in s for t in OWNERSHIP_TERMS))
x["third_party_language"]=ctx.map(lambda s:any(t in s for t in THIRD_PARTY_TERMS))
x["context_signal"]="neither"
x.loc[x["ownership_language"] & ~x["third_party_language"],"context_signal"]="ownership_only"
x.loc[~x["ownership_language"] & x["third_party_language"],"context_signal"]="third_party_only"
x.loc[x["ownership_language"] & x["third_party_language"],"context_signal"]="mixed"
report={
 "common_equity_cusip_rows":int(len(x)),
 "issuers":int(x["cik"].nunique()) if len(x) else 0,
 "unique_cusips":int(x["identifier"].nunique()) if len(x) else 0,
 "by_filing_form":{str(k):int(v) for k,v in x["filing_form"].fillna("UNKNOWN").value_counts().to_dict().items()},
 "by_document_selection_reason":{str(k):int(v) for k,v in x["document_selection_reason"].fillna("UNKNOWN").value_counts().to_dict().items()},
 "by_context_signal":{str(k):int(v) for k,v in x["context_signal"].value_counts().to_dict().items()},
 "unique_cusips_by_context_signal":{str(k):int(v) for k,v in x.groupby("context_signal")["identifier"].nunique().to_dict().items()},
}
out=Path("artifacts/identity/sec-cusip-ownership-composition");out.mkdir(parents=True,exist_ok=True)
x[["cik","accession","filing_form","document_name","document_selection_reason","identifier","identifier_match_start","identifier_match_end","context_signal"]].to_parquet(out/"cusip_context_composition.parquet",index=False)
(out/"cusip_context_composition.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps(report,indent=2))
