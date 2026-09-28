from __future__ import annotations
import hashlib
import pandas as pd
from finrisk.identity.sec_13f_source_index import preflight,assert_preflight,resolve
from finrisk.identity.sec_13f_coverage_probe import observation_quarters,list_name_key

DEFAULT_CONTROLS=("APPLE INC","MICROSOFT CORP")

def required_vintages(cases:pd.DataFrame)->list[str]:
    qs=sorted({q for _,r in cases.iterrows() for q in observation_quarters(r["last_filing"])})
    return [f"{y}Q{q}" for y,q in qs]

def run_coverage_orchestration(cases:pd.DataFrame,aliases:pd.DataFrame,manifest:dict,
                               load_source,parse_source,controls=DEFAULT_CONTROLS)->dict:
    vintages=required_vintages(cases)
    pf=preflight(manifest,vintages);assert_preflight(pf)
    results=[];sources={}
    for vintage in vintages:
        source=resolve(manifest,vintage)
        content=load_source(source)
        frame,fidelity=parse_source(source,content)
        keys=set(frame["issuer_name"].map(list_name_key))
        control_hits={c:list_name_key(c) in keys for c in controls}
        if not all(control_hits.values()):
            raise ValueError(f"Positive control failure {vintage}: {control_hits}")
        sources[vintage]={"url":source.url,"format":source.fmt,"sha256":hashlib.sha256(content).hexdigest(),
                          "bytes":len(content),"fidelity":fidelity,"controls":control_hits}
        year,q=int(vintage[:4]),int(vintage[-1])
        for _,case in cases.iterrows():
            if (year,q) not in observation_quarters(case["last_filing"]):continue
            cik=str(case["cik"])
            names=aliases.loc[aliases["cik"].astype(str).eq(cik),"name"].dropna().astype(str).tolist()
            hits=sorted({list_name_key(n) for n in names}&keys)
            results.append({"cik":cik,"vintage":vintage,"exact_discovery_hit":bool(hits),"matched_keys":hits})
    return {"cases":cases[["cik","last_filing"]].astype(str).to_dict("records"),"observations":results,"sources":sources,
            "case_count":len(cases),"observation_count":len(results),
            "exact_hit_observations":sum(r["exact_discovery_hit"] for r in results)}
