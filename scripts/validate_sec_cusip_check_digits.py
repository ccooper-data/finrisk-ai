from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def char_value(c):
    if c.isdigit(): return int(c)
    if "A"<=c<="Z": return ord(c)-ord("A")+10
    return {"*":36,"@":37,"#":38}.get(c)

def valid_cusip(value):
    s=str(value).strip().upper()
    if len(s)!=9 or any(char_value(c) is None for c in s): return False
    total=0
    for i,c in enumerate(s[:8]):
        v=char_value(c)*(2 if i%2 else 1)
        total += v//10 + v%10
    expected=(10-(total%10))%10
    return s[8].isdigit() and int(s[8])==expected

d=pd.read_parquet("artifacts/source/pilot/tier_a_identifier_evidence.parquet")
x=d[d["identifier_type"].eq("CUSIP")].copy()
x["cusip_check_digit_valid"]=x["identifier"].map(valid_cusip)
common=x[x["common_equity_context"].fillna(False)]
report={
 "cusip_rows":int(len(x)),
 "cusip_unique":int(x["identifier"].nunique()),
 "valid_rows":int(x["cusip_check_digit_valid"].sum()),
 "valid_unique":int(x.loc[x["cusip_check_digit_valid"],"identifier"].nunique()),
 "common_equity_rows":int(len(common)),
 "common_equity_valid_rows":int(common["cusip_check_digit_valid"].sum()),
 "common_equity_unique":int(common["identifier"].nunique()),
 "common_equity_valid_unique":int(common.loc[common["cusip_check_digit_valid"],"identifier"].nunique()),
}
out=Path("artifacts/identity/cusip-validity");out.mkdir(parents=True,exist_ok=True)
(out/"cusip_validity.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps(report,indent=2))
