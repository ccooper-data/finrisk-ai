from __future__ import annotations
import re
import pandas as pd
from finrisk.identity.resolution import normalize_entity_name

ABBREV={"HOLDINGS":"HLDGS","HOLDING":"HLDG","INTERNATIONAL":"INTL","LIMITED":"LTD","ASSURANCE":"ASSUR","GENERATION":"GENERAT","CORPORATION":"CORP","COMPANY":"CO","INCORPORATED":"INC"}

def list_name_key(name:str,width:int=28)->str:
    s=normalize_entity_name(name)
    tokens=[ABBREV.get(t,t) for t in s.split()]
    return " ".join(tokens)[:width].rstrip()

def quarter_index(year:int,quarter:int)->int:return year*4+(quarter-1)
def quarter_from_index(x:int)->tuple[int,int]:return x//4,x%4+1

def observation_quarters(last_filing)->list[tuple[int,int]]:
    t=pd.Timestamp(last_filing);q=(t.month-1)//3+1;base=quarter_index(t.year,q)
    return [quarter_from_index(base-o) for o in (0,4,8,12)]

def select_five_cases(hard:pd.DataFrame)->pd.DataFrame:
    x=hard.copy().sort_values(["last_filing","cik"]).reset_index(drop=True)
    if len(x)<5:raise ValueError("Need at least five hard cases")
    idx=[round(i*(len(x)-1)/4) for i in range(5)]
    return x.iloc[idx].copy().reset_index(drop=True)

def name_hits(aliases:list[str],official_names:list[str])->dict:
    a={list_name_key(x) for x in aliases if str(x).strip()}
    o={list_name_key(x) for x in official_names if str(x).strip()}
    exact=sorted(a&o)
    return {"exact_keys":exact,"exact_hit":bool(exact)}
