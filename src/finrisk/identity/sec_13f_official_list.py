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
