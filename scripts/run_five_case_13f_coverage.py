from __future__ import annotations
import hashlib,io,json,os,time
from pathlib import Path
import httpx,pandas as pd,pdfplumber
from finrisk.identity.sec_13f_positional import OFFICIAL_LIST_BOUNDS,COPYRIGHT_COVER_PAGES,parse_page_words,page_fidelity_report,assert_equity_cusip_fidelity
from finrisk.identity.sec_13f_official_list import parse_official_13f_fixed_width,text_list_fidelity,assert_text_list_fidelity
from finrisk.identity.sec_13f_source_index import preflight,assert_preflight,resolve
from finrisk.identity.sec_13f_coverage_probe import select_five_cases,observation_quarters,list_name_key

CONTROLS=("APPLE INC","MICROSOFT CORP")
SPACING=1.5
ua=os.environ["SEC_USER_AGENT"]
if "@" not in ua:raise ValueError("SEC_USER_AGENT must identify contact email")
headers={"User-Agent":ua,"Accept-Encoding":"gzip, deflate"}

def fetch(client,url):
    for attempt in range(4):
        r=client.get(url,headers=headers,timeout=120,follow_redirects=True)
        if r.status_code in (403,429,503) and attempt<3:
            time.sleep(SPACING*(2**(attempt+1)));continue
        r.raise_for_status();return r.content
    raise RuntimeError(url)

identity=pd.read_parquet("artifacts/source/identity/historical_identity_master.parquet")
aliases=pd.read_parquet("artifacts/source/names/sec_filing_names.parquet")
hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
hard=hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(100)
cases=select_five_cases(hard)
results=[];sources={}
with httpx.Client() as client:
  quarters=sorted({q for _,r in cases.iterrows() for q in observation_quarters(r["last_filing"])})
  for year,q in quarters:
    vintage=f"{year}Q{q}";url=f"https://www.sec.gov/divisions/investment/13f/13flist{year}q{q}.pdf"
    content=fetch(client,url);frames=[];tot={"candidate_rows":0,"option_rows":0,"equity_rows":0,"equity_cusip_valid":0}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
      for idx,page in enumerate(pdf.pages):
        if idx<COPYRIGHT_COVER_PAGES:continue
        words=page.extract_words(use_text_flow=False,keep_blank_chars=False)
        rep=page_fidelity_report(words,OFFICIAL_LIST_BOUNDS)
        for k in tot:tot[k]+=rep[k]
        f=parse_page_words(words,OFFICIAL_LIST_BOUNDS)
        if len(f):frames.append(f)
    tot["equity_valid_rate"]=tot["equity_cusip_valid"]/tot["equity_rows"] if tot["equity_rows"] else 0
    assert_equity_cusip_fidelity(tot,vintage)
    frame=pd.concat(frames,ignore_index=True).drop_duplicates()
    keys=set(frame["issuer_name"].map(list_name_key))
    control_hits={c:list_name_key(c) in keys for c in CONTROLS}
    if not all(control_hits.values()):raise ValueError(f"Positive control failure {vintage}: {control_hits}")
    sources[vintage]={"url":url,"format":source.fmt,"sha256":hashlib.sha256(content).hexdigest(),"bytes":len(content),"fidelity":tot,"controls":control_hits}
    for _,case in cases.iterrows():
      if (year,q) not in observation_quarters(case["last_filing"]):continue
      cik=str(case["cik"])
      names=aliases.loc[aliases["cik"].astype(str).eq(cik),"name"].dropna().astype(str).tolist()
      alias_keys={list_name_key(n) for n in names}
      hits=sorted(alias_keys & keys)
      results.append({"cik":cik,"vintage":vintage,"exact_discovery_hit":bool(hits),"matched_keys":hits})
    time.sleep(SPACING)
report={"cases":cases[["cik","last_filing"]].astype(str).to_dict("records"),"observations":results,"sources":sources,
        "case_count":len(cases),"observation_count":len(results),"exact_hit_observations":sum(r["exact_discovery_hit"] for r in results)}
out=Path("artifacts/identity/five-case-13f-coverage");out.mkdir(parents=True,exist_ok=True)
(out/"coverage.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps({"case_count":report["case_count"],"observation_count":report["observation_count"],"exact_hit_observations":report["exact_hit_observations"],
                  "cases":report["cases"],"controls_by_vintage":{k:v["controls"] for k,v in sources.items()}},indent=2))
