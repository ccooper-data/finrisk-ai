from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from finrisk.identity.identifier_corroboration import valid_cusip
from finrisk.identity.candidate_discovery import name_similarity
from finrisk.identity.resolution import normalize_entity_name

@dataclass(frozen=True)
class Official13FRow:
    cusip:str
    issuer_name:str
    issuer_description:str
    status:str

def parse_official_13f_text(text:str)->pd.DataFrame:
    rows=[]
    for line in (text or "").splitlines():
        if len(line)<40:continue
        cusip=line[0:9].strip().upper()
        if not valid_cusip(cusip):continue
        issuer=line[10:40].strip()
        desc=line[40:67].strip() if len(line)>=67 else ""
        status=line[67:70].strip() if len(line)>=70 else ""
        if not normalize_entity_name(issuer):continue
        rows.append({"cusip":cusip,"issuer_name":issuer,"issuer_description":desc,"status":status})
    return pd.DataFrame(rows).drop_duplicates()

def measure_name_coverage(hard_cases:pd.DataFrame,aliases:pd.DataFrame,official:pd.DataFrame,min_score:float=.90)->tuple[pd.DataFrame,dict]:
    rows=[]
    for _,h in hard_cases.iterrows():
        cik=str(h["cik"])
        names=aliases.loc[aliases["cik"].astype(str).eq(cik),"name"].dropna().astype(str).tolist()
        best=0.0;best_name=None;best_cusip=None;exact=False
        for _,s in official.iterrows():
            for name in names:
                score=name_similarity(name,str(s["issuer_name"]))
                if score>best:
                    best=score;best_name=s["issuer_name"];best_cusip=s["cusip"]
                if normalize_entity_name(name)==normalize_entity_name(str(s["issuer_name"])):
                    exact=True
        rows.append({"cik":cik,"alias_count":len(names),"best_score":best,"best_official_name":best_name,
                     "best_cusip":best_cusip,"exact_normalized_name_hit":exact,"candidate_hit":best>=min_score})
    d=pd.DataFrame(rows)
    report={"hard_cases":len(d),"candidate_hits":int(d["candidate_hit"].sum()),
            "exact_normalized_name_hits":int(d["exact_normalized_name_hit"].sum()),
            "unique_valid_cusips":int(d.loc[d["candidate_hit"],"best_cusip"].nunique()),
            "min_score":min_score}
    return d,report


# --- Fixed-width TXT format (2020Q1 onward) ------------------------------------
#
# Derived from 13flist2024q1.txt: every line is exactly 80 characters, with no
# header, preamble, page furniture or copyright cover page. Always-blank
# separator columns sit at 38-39, 56-66 and 70-78, giving:
#
#   [0:9]   CUSIP
#   [9]     "*" marker (distinct from the STATUS column below)
#   [10:38] issuer name, truncated to 28 characters
#   [40:56] issuer description
#   [67:70] status: "*A*" added, "*D*" deleted, blank otherwise
#   [79]    single-character type code (observed: E N P S U A; meaning TBD)
#
# Verified: 11,291/11,291 rows check-digit valid on 2024Q1.
TEXT_LINE_WIDTH=80
TEXT_FIELDS={"cusip":(0,9),"marker":(9,10),"issuer_name":(10,38),
             "issuer_description":(40,56),"status":(67,70),"type_code":(79,80)}
STATUS_ADDED="*A*"
STATUS_DELETED="*D*"


def parse_official_13f_fixed_width(text:str)->pd.DataFrame:
    """Strict parser for the fixed-width TXT lists.

    `*A*`/`*D*` are recorded as list membership changes, NOT as exchange
    listing events: a `*D*` row evidences that the security left the section
    13(f) list in that quarter, which is not yet established to be equivalent
    to exchange delisting. Callers must corroborate the SEC's semantics before
    treating `deleted_from_13f_list` as a delisting date.
    """
    rows=[]
    for line in (text or "").splitlines():
        if len(line)!=TEXT_LINE_WIDTH: continue
        get=lambda k:line[TEXT_FIELDS[k][0]:TEXT_FIELDS[k][1]]
        cusip=get("cusip").strip().upper()
        if not valid_cusip(cusip): continue
        issuer=get("issuer_name").strip()
        if not normalize_entity_name(issuer): continue
        status=get("status").strip()
        rows.append({"cusip":cusip,"issuer_name":issuer,
                     "issuer_description":get("issuer_description").strip(),
                     "status":status,"marker":get("marker").strip(),
                     "type_code":get("type_code").strip(),
                     "added_to_13f_list":status==STATUS_ADDED,
                     "deleted_from_13f_list":status==STATUS_DELETED})
    return pd.DataFrame(rows).drop_duplicates()


def text_list_fidelity(text:str)->dict:
    """Pre-filter counts, so a format change cannot masquerade as low coverage."""
    lines=(text or "").splitlines()
    widths={len(l) for l in lines if l.strip()}
    conforming=[l for l in lines if len(l)==TEXT_LINE_WIDTH]
    candidates=[l for l in conforming if l[0:9].strip()]
    valid=[l for l in candidates if valid_cusip(l[0:9].strip().upper())]
    return {"lines":len(lines),"distinct_widths":sorted(widths),
            "conforming_lines":len(conforming),"candidate_rows":len(candidates),
            "cusip_valid_rows":len(valid),
            "cusip_valid_rate":(len(valid)/len(candidates)) if candidates else 0.0}


def assert_text_list_fidelity(report:dict,vintage:str,min_rows:int=1000)->None:
    """Fail closed: the TXT lists are 100% check-digit valid when parsed correctly."""
    if report["distinct_widths"] not in ([TEXT_LINE_WIDTH],[]):
        raise ValueError(f"Unexpected TXT line widths for {vintage}: {report}")
    if report["candidate_rows"]<min_rows:
        raise ValueError(f"TXT row floor failed for {vintage}: {report}")
    if report["cusip_valid_rows"]!=report["candidate_rows"]:
        raise ValueError(f"TXT CUSIP validity below 100% for {vintage}: {report}")


def list_membership_events(frame:pd.DataFrame,vintage:str)->pd.DataFrame:
    """Dated 13(f)-list membership changes for one vintage.

    Deliberately named for what the evidence is. Equating
    `deleted_from_13f_list_quarter` with a delisting date requires separate
    corroboration of SEC `*D*` semantics.
    """
    changed=frame[frame["added_to_13f_list"]|frame["deleted_from_13f_list"]].copy()
    changed["event"]=changed["deleted_from_13f_list"].map({True:"deleted_from_13f_list",False:"added_to_13f_list"})
    changed["deleted_from_13f_list_quarter"]=changed["deleted_from_13f_list"].map(lambda x:vintage if x else None)
    changed["added_to_13f_list_quarter"]=changed["added_to_13f_list"].map(lambda x:vintage if x else None)
    return changed[["cusip","issuer_name","issuer_description","event",
                    "added_to_13f_list_quarter","deleted_from_13f_list_quarter"]].reset_index(drop=True)
