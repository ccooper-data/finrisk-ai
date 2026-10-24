from __future__ import annotations
from difflib import SequenceMatcher
from finrisk.identity.sec_13f_coverage_probe import list_name_key

def rank_near_misses(aliases:list[str],official_names:list[str],limit:int=5)->list[dict]:
    aks=sorted({list_name_key(x) for x in aliases if str(x).strip()})
    oks=sorted({list_name_key(x) for x in official_names if str(x).strip()})
    scored=[]
    for a in aks:
        for o in oks:
            scored.append((SequenceMatcher(None,a,o).ratio(),a,o))
    scored.sort(reverse=True)
    return [{"score":s,"alias_key":a,"official_key":o} for s,a,o in scored[:limit]]

def exact_keys(aliases:list[str],official_names:list[str])->list[str]:
    return sorted({list_name_key(x) for x in aliases}&{list_name_key(x) for x in official_names})
