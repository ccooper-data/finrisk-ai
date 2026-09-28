from __future__ import annotations
import hashlib,json,io,os
from pathlib import Path
import httpx,pdfplumber
from finrisk.identity.sec_13f_positional import ColumnBounds,parse_page_words

SOURCES={"2009Q4":"https://www.sec.gov/divisions/investment/13f/13flist2009q4.pdf",
         "2010Q4":"https://www.sec.gov/divisions/investment/13f/13flist2010q4.pdf",
         "2011Q1":"https://www.sec.gov/divisions/investment/13f/13flist2011q1.pdf"}
# Initial bounds are explicit probe parameters, not production constants.
BOUNDS=ColumnBounds(35,115,330,500)
ua=os.environ["SEC_USER_AGENT"]
if "@" not in ua: raise ValueError("SEC_USER_AGENT must identify a contact email")
headers={"User-Agent":ua,"Accept-Encoding":"gzip, deflate"}
out=[]
for vintage,url in SOURCES.items():
    r=httpx.get(url,headers=headers,timeout=120,follow_redirects=True);r.raise_for_status()
    rows=[];page_counts=[]
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for page in pdf.pages:
            words=page.extract_words(use_text_flow=False,keep_blank_chars=False)
            d=parse_page_words(words,BOUNDS)
            page_counts.append(len(d))
            if len(d):rows.append(d)
    import pandas as pd
    frame=pd.concat(rows,ignore_index=True).drop_duplicates() if rows else pd.DataFrame()
    rec={"vintage":vintage,"url":url,"sha256":hashlib.sha256(r.content).hexdigest(),"bytes":len(r.content),
         "pages":len(page_counts),"parsed_rows":int(len(frame)),"nonempty_pages":int(sum(x>0 for x in page_counts)),
         "unique_cusips":int(frame["cusip"].nunique()) if len(frame) else 0,
         "unique_issuers":int(frame["issuer_name"].nunique()) if len(frame) else 0,
         "min_nonzero_page_rows":int(min([x for x in page_counts if x>0],default=0)),
         "max_page_rows":int(max(page_counts,default=0))}
    if rec["parsed_rows"]<1000 or rec["unique_cusips"]<1000 or rec["nonempty_pages"]<50:
        raise ValueError(f"Positional fidelity floor failed for {vintage}: {rec}")
    out.append(rec)
path=Path("artifacts/identity/sec-13f-positional-fidelity");path.mkdir(parents=True,exist_ok=True)
(path/"fidelity.json").write_text(json.dumps({"vintages":out},indent=2,sort_keys=True))
print(json.dumps({"vintages":out},indent=2))
