from __future__ import annotations
import io,json,os,time
from pathlib import Path
import httpx,pandas as pd,pdfplumber
from finrisk.identity.sec_13f_positional import OFFICIAL_LIST_BOUNDS,COPYRIGHT_COVER_PAGES,parse_page_words,page_fidelity_report,assert_equity_cusip_fidelity
from finrisk.identity.sec_13f_official_list import parse_official_13f_fixed_width,text_list_fidelity,assert_text_list_fidelity
from finrisk.identity.sec_13f_coverage_probe import select_five_cases
from finrisk.identity.sec_13f_live_probe import run_coverage_orchestration

SPACING=1.5
ua=os.environ["SEC_USER_AGENT"]
if "@" not in ua:raise ValueError("SEC_USER_AGENT must identify contact email")
headers={"User-Agent":ua,"Accept":"application/pdf,text/plain,*/*;q=0.8","Accept-Encoding":"gzip, deflate"}
client=httpx.Client()

def load_source(source):
    for attempt in range(4):
        r=client.get(source.url,headers=headers,timeout=120,follow_redirects=True)
        if r.status_code in (403,429,503) and attempt<3:
            time.sleep(SPACING*(2**(attempt+1)));continue
        r.raise_for_status();return r.content
    raise RuntimeError(source.url)

def parse_source(source,content):
    if source.fmt=="txt":
        text=content.decode("utf-8",errors="replace")
        rep=text_list_fidelity(text);assert_text_list_fidelity(rep,source.vintage)
        return parse_official_13f_fixed_width(text),rep
    frames=[];tot={"candidate_rows":0,"option_rows":0,"equity_rows":0,"equity_cusip_valid":0}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for idx,page in enumerate(pdf.pages):
            if idx<COPYRIGHT_COVER_PAGES:continue
            words=page.extract_words(use_text_flow=False,keep_blank_chars=False)
            rep=page_fidelity_report(words,OFFICIAL_LIST_BOUNDS)
            for k in tot:tot[k]+=rep[k]
            frame=parse_page_words(words,OFFICIAL_LIST_BOUNDS)
            if len(frame):frames.append(frame)
    tot["equity_valid_rate"]=tot["equity_cusip_valid"]/tot["equity_rows"] if tot["equity_rows"] else 0
    assert_equity_cusip_fidelity(tot,source.vintage)
    return pd.concat(frames,ignore_index=True).drop_duplicates(),tot

identity=pd.read_parquet("artifacts/source/identity/historical_identity_master.parquet")
aliases=pd.read_parquet("artifacts/source/names/sec_filing_names.parquet")
manifest=json.loads(Path("artifacts/source/13f-manifest/source_manifest.json").read_text())
hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
hard=hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(100)
cases=select_five_cases(hard)
report=run_coverage_orchestration(cases,aliases,manifest,load_source,parse_source)
client.close()
out=Path("artifacts/identity/five-case-13f-coverage");out.mkdir(parents=True,exist_ok=True)
(out/"coverage.json").write_text(json.dumps(report,indent=2,sort_keys=True))
print(json.dumps({"case_count":report["case_count"],"observation_count":report["observation_count"],
                  "exact_hit_observations":report["exact_hit_observations"],"cases":report["cases"],
                  "controls_by_vintage":{k:v["controls"] for k,v in report["sources"].items()}},indent=2))
