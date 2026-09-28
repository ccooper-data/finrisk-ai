"""Resolve each 13F official-list vintage to its actual SEC source URL.

The SEC does not publish these lists under a single URL template:

  * 1996Q1-2021Q1 live under /divisions/investment/13f/13flist<vintage>.pdf
  * 2021Q2 onward live under /files/investment/13flist<vintage>.pdf
    (the "/13f/" path segment disappears)
  * 2020Q1 onward are additionally published as fixed-width TXT
  * some filenames carry a "-txt" infix, e.g. 13flist2025q3-txt.txt
  * some quarters are simply absent (no 1997Q4, no 2004Q1)

So the index page is the authority, not a pattern. Build the manifest once,
freeze it, and resolve from the frozen artifact -- rather than constructing a
URL per quarter and discovering a 404 halfway through an expensive run.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict

INDEX_URL="https://www.sec.gov/rules-regulations/staff-guidance/official-list-section-13f-securities"
SEC_ORIGIN="https://www.sec.gov"

# 13flist2009q4.pdf / 13flist2025q3-txt.txt
HREF_RE=re.compile(r'href="(?P<path>[^"]*?/13flist(?P<year>\d{4})q(?P<quarter>[1-4])(?:-txt)?\.(?P<ext>pdf|txt))"',re.I)

# TXT is a fixed-width 80-column format with no page furniture and no
# copyright cover page; prefer it wherever the SEC published one.
FORMAT_PREFERENCE=("txt","pdf")


@dataclass(frozen=True)
class VintageSource:
    vintage:str
    year:int
    quarter:int
    fmt:str
    url:str


def vintage_label(year:int,quarter:int)->str: return f"{year}Q{quarter}"


def parse_source_index(html:str)->dict[str,dict[str,str]]:
    """Map vintage -> {format: absolute url} from the index page HTML."""
    found:dict[str,dict[str,str]]={}
    for m in HREF_RE.finditer(html or ""):
        path=m.group("path")
        url=path if path.startswith("http") else SEC_ORIGIN+("" if path.startswith("/") else "/")+path
        label=vintage_label(int(m.group("year")),int(m.group("quarter")))
        found.setdefault(label,{}).setdefault(m.group("ext").lower(),url)
    return found


def preferred_source(sources:dict[str,str])->tuple[str,str]|None:
    for fmt in FORMAT_PREFERENCE:
        if sources.get(fmt): return fmt,sources[fmt]
    return None


def build_manifest(html:str)->dict:
    """Frozen vintage -> source manifest, with formats recorded per vintage."""
    index=parse_source_index(html)
    entries=[]
    for label in sorted(index,key=lambda s:(int(s[:4]),int(s[-1]))):
        chosen=preferred_source(index[label])
        if chosen is None: continue
        fmt,url=chosen
        year,quarter=int(label[:4]),int(label[-1])
        entries.append({"vintage":label,"year":year,"quarter":quarter,"format":fmt,"url":url,
                        "available_formats":sorted(index[label])})
    return {"index_url":INDEX_URL,"vintages":entries,"vintage_count":len(entries)}


def resolve(manifest:dict,vintage:str)->VintageSource:
    """Resolve one vintage, distinguishing 'unavailable' from a bad guess."""
    for e in manifest.get("vintages",[]):
        if e["vintage"].upper()==vintage.upper():
            return VintageSource(e["vintage"],e["year"],e["quarter"],e["format"],e["url"])
    raise KeyError(f"Vintage {vintage} is not published in the SEC official-list index")


def missing_quarters(manifest:dict,first:str,last:str)->list[str]:
    """Quarters in [first,last] the SEC never published -- genuinely absent,
    not a resolution failure."""
    have={e["vintage"] for e in manifest.get("vintages",[])}
    def idx(v:str)->int: return int(v[:4])*4+int(v[-1])-1
    out=[]
    for i in range(idx(first),idx(last)+1):
        label=vintage_label(i//4,i%4+1)
        if label not in have: out.append(label)
    return out


def preflight(manifest:dict,vintages:list[str])->dict:
    """Validate every required vintage BEFORE any retrieval begins."""
    resolved,unavailable=[],[]
    for v in vintages:
        try: resolved.append(asdict(resolve(manifest,v)))
        except KeyError: unavailable.append(v)
    return {"requested":list(vintages),"resolved":resolved,"unavailable":unavailable,
            "all_resolved":not unavailable}


def assert_preflight(report:dict)->None:
    if not report["all_resolved"]:
        raise ValueError(f"Unresolved 13F list vintages before retrieval: {report['unavailable']}")
