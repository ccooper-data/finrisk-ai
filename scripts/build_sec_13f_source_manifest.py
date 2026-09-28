"""Freeze the SEC 13F official-list source manifest, then preflight it.

Retrieval order is deliberate: resolve every required vintage from the index
FIRST, fail closed on anything unresolved, and only then let downstream jobs
download. A bad URL must surface in seconds, not after minutes of PDF parsing.
"""
from __future__ import annotations
import hashlib,json,os,time
from pathlib import Path
import httpx
from finrisk.identity.sec_13f_source_index import (
    INDEX_URL,build_manifest,missing_quarters,preflight,assert_preflight,
)

FIRST_VINTAGE=os.environ.get("FIRST_13F_VINTAGE","1996Q1")
LAST_VINTAGE=os.environ.get("LAST_13F_VINTAGE","2026Q2")
REQUEST_SPACING_SECONDS=1.5
MAX_ATTEMPTS=4

ua=os.environ["SEC_USER_AGENT"]
if "@" not in ua: raise ValueError("SEC_USER_AGENT must identify a contact email")
# SEC's CDN rejects requests without an Accept header, and answers bursts with
# "Request Rate Threshold Exceeded" as a 403 -- not an authorization failure.
headers={"User-Agent":ua,"Accept":"text/html,application/xhtml+xml,*/*;q=0.8",
         "Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate"}

def fetch(client:httpx.Client,url:str)->bytes:
    for attempt in range(1,MAX_ATTEMPTS+1):
        r=client.get(url,headers=headers,timeout=120,follow_redirects=True)
        if r.status_code in (403,429,503) and attempt<MAX_ATTEMPTS:
            time.sleep(REQUEST_SPACING_SECONDS*(2**attempt))
            continue
        r.raise_for_status()
        return r.content
    raise RuntimeError(f"Exhausted retries for {url}")

def vintage_range(first:str,last:str)->list[str]:
    def idx(v:str)->int: return int(v[:4])*4+int(v[-1])-1
    return [f"{i//4}Q{i%4+1}" for i in range(idx(first),idx(last)+1)]

with httpx.Client() as client:
    html=fetch(client,INDEX_URL).decode("utf-8",errors="replace")

manifest=build_manifest(html)
manifest["index_sha256"]=hashlib.sha256(html.encode("utf-8")).hexdigest()
manifest["first_vintage"]=manifest["vintages"][0]["vintage"] if manifest["vintages"] else None
manifest["last_vintage"]=manifest["vintages"][-1]["vintage"] if manifest["vintages"] else None
manifest["missing_quarters"]=missing_quarters(manifest,FIRST_VINTAGE,LAST_VINTAGE)
manifest["format_counts"]={f:sum(1 for e in manifest["vintages"] if e["format"]==f) for f in ("txt","pdf")}

if manifest["vintage_count"]<100:
    raise ValueError(f"Source index yielded too few vintages: {manifest['vintage_count']}")

requested=[v for v in vintage_range(FIRST_VINTAGE,LAST_VINTAGE) if v not in manifest["missing_quarters"]]
report=preflight(manifest,requested)
assert_preflight(report)

out=Path("artifacts/identity/sec-13f-source-manifest");out.mkdir(parents=True,exist_ok=True)
(out/"source_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True))
(out/"preflight.json").write_text(json.dumps(
    {k:report[k] for k in ("requested","unavailable","all_resolved")},indent=2,sort_keys=True))
print(json.dumps({k:manifest[k] for k in
    ("index_url","index_sha256","vintage_count","first_vintage","last_vintage",
     "format_counts","missing_quarters")},indent=2,sort_keys=True))
