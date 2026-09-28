from __future__ import annotations
import hashlib,io,json,os,time
from pathlib import Path
import httpx,pandas as pd,pdfplumber
from finrisk.identity.sec_13f_positional import (
    OFFICIAL_LIST_BOUNDS,COPYRIGHT_COVER_PAGES,parse_page_words,
    page_fidelity_report,assert_equity_cusip_fidelity,
)

# Vintages verified locally against OFFICIAL_LIST_BOUNDS (100% equity CUSIP
# validity on each). Spans 2009-2020 to exercise layout drift, not just one year.
SOURCES={
 "2009Q4":"https://www.sec.gov/divisions/investment/13f/13flist2009q4.pdf",
 "2010Q2":"https://www.sec.gov/divisions/investment/13f/13flist2010q2.pdf",
 "2011Q3":"https://www.sec.gov/divisions/investment/13f/13flist2011q3.pdf",
 "2015Q1":"https://www.sec.gov/divisions/investment/13f/13flist2015q1.pdf",
 "2020Q1":"https://www.sec.gov/divisions/investment/13f/13flist2020q1.pdf",
}
REQUEST_SPACING_SECONDS=1.5
MAX_ATTEMPTS=4

ua=os.environ["SEC_USER_AGENT"]
if "@" not in ua: raise ValueError("SEC_USER_AGENT must identify a contact email")
headers={"User-Agent":ua,"Accept-Encoding":"gzip, deflate"}

def fetch(client:httpx.Client,url:str)->bytes:
    """SEC throttles bursts with 403/429; back off rather than hammering."""
    for attempt in range(1,MAX_ATTEMPTS+1):
        r=client.get(url,headers=headers,timeout=120,follow_redirects=True)
        if r.status_code in (403,429,503) and attempt<MAX_ATTEMPTS:
            time.sleep(REQUEST_SPACING_SECONDS*(2**attempt))
            continue
        r.raise_for_status()
        return r.content
    raise RuntimeError(f"Exhausted retries for {url}")

out=[]
with httpx.Client() as client:
    for vintage,url in SOURCES.items():
        content=fetch(client,url)
        frames=[];page_rows=[];totals={"candidate_rows":0,"option_rows":0,"equity_rows":0,"equity_cusip_valid":0}
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages=len(pdf.pages)
            for index,page in enumerate(pdf.pages):
                if index<COPYRIGHT_COVER_PAGES: continue
                words=page.extract_words(use_text_flow=False,keep_blank_chars=False)
                report=page_fidelity_report(words,OFFICIAL_LIST_BOUNDS)
                for key in totals: totals[key]+=report[key]
                frame=parse_page_words(words,OFFICIAL_LIST_BOUNDS)
                page_rows.append(len(frame))
                if len(frame): frames.append(frame)
        totals["equity_valid_rate"]=(totals["equity_cusip_valid"]/totals["equity_rows"]) if totals["equity_rows"] else 0.0
        assert_equity_cusip_fidelity(totals,vintage)
        frame=pd.concat(frames,ignore_index=True).drop_duplicates() if frames else pd.DataFrame()
        rec={"vintage":vintage,"url":url,"sha256":hashlib.sha256(content).hexdigest(),"bytes":len(content),
             "pages":pages,"parsed_rows":int(len(frame)),"nonempty_pages":int(sum(x>0 for x in page_rows)),
             "unique_cusips":int(frame["cusip"].nunique()) if len(frame) else 0,
             "unique_issuers":int(frame["issuer_name"].nunique()) if len(frame) else 0,
             "min_nonzero_page_rows":int(min([x for x in page_rows if x>0],default=0)),
             "max_page_rows":int(max(page_rows,default=0)),"fidelity":totals}
        if rec["parsed_rows"]<1000 or rec["unique_cusips"]<1000 or rec["nonempty_pages"]<50:
            raise ValueError(f"Positional fidelity floor failed for {vintage}: {rec}")
        out.append(rec)
        time.sleep(REQUEST_SPACING_SECONDS)

path=Path("artifacts/identity/sec-13f-positional-fidelity");path.mkdir(parents=True,exist_ok=True)
(path/"fidelity.json").write_text(json.dumps({"vintages":out},indent=2,sort_keys=True))
print(json.dumps({"vintages":out},indent=2))
