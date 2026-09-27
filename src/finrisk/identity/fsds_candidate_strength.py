from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from finrisk.identity.candidate_discovery import discover_candidates
from finrisk.identity.fsds_discovery_impact import alias_map
from finrisk.identity.sec_fsds_names import normalize_cik

def _candidate_isin(top_row)->str|None:
    if top_row is None:return None
    value=top_row.get("isin")
    if pd.isna(value):return None
    normalized=str(value).strip().upper()
    return normalized or None

def candidate_strength(identity:pd.DataFrame,filing_names:pd.DataFrame,universe:pd.DataFrame,
                       min_score:float=.45,limit:int=100)->tuple[pd.DataFrame,dict]:
    amap=alias_map(filing_names);rows=[]
    hard=identity[(identity["distress_observations"]>0)&(~identity["has_current_ticker"])].copy()
    hard=hard.sort_values(["first_filing","distress_observations"],ascending=[True,False]).head(limit)
    for _,r in hard.iterrows():
        cik=normalize_cik(r["cik"]);base=r["historical_names"] if isinstance(r["historical_names"],list) else []
        aliases=sorted(set(base+amap.get(cik,[])))
        cand=discover_candidates(cik,aliases,universe,min_score=min_score,limit=5).reset_index(drop=True)
        top=float(cand.loc[0,"discovery_score"]) if len(cand) else None
        second=float(cand.loc[1,"discovery_score"]) if len(cand)>1 else None
        margin=(top-second) if top is not None and second is not None else (top if top is not None else None)
        top_row=cand.iloc[0] if len(cand) else None
        isin=_candidate_isin(top_row)
        tied=bool(top is not None and second is not None and abs(top-second)<1e-12)
        near_tied=bool(top is not None and second is not None and (top-second)<.02)
        rows.append({"cik":cik,"candidate_count":len(cand),"top_security_id":top_row["security_id"] if top_row is not None else None,
                     "top_security_name":top_row["security_name"] if top_row is not None else None,
                     "top_score":top,"second_score":second,"margin":margin,"top_score_tied":tied,"top_score_near_tied":near_tied,\n                     "top_tied_candidate_count":int(cand["discovery_score"].eq(top).sum()) if top is not None else 0,\n                     "top_tied_security_ids":cand.loc[cand["discovery_score"].eq(top),"security_id"].astype(str).tolist() if top is not None else [],\n                     "top_tied_security_names":cand.loc[cand["discovery_score"].eq(top),"security_name"].astype(str).tolist() if top is not None else [],\n                     "top_tied_isins":cand.loc[cand["discovery_score"].eq(top),"isin"].fillna("").astype(str).tolist() if top is not None else [],
                     "is_delisted":bool(top_row["is_delisted"]) if top_row is not None and pd.notna(top_row.get("is_delisted")) else None,
                     "isin":isin,"isin_present":isin is not None,
                     "high_margin":bool(top is not None and top>=.90 and margin is not None and margin>=.08)})
    d=pd.DataFrame(rows)
    report={"issuers":len(d),"with_candidate":int((d["candidate_count"]>0).sum()),
            "top_score_ge_090":int((d["top_score"]>=.90).sum()),"high_margin_candidates":int(d["high_margin"].sum()),
            "top_score_ties":int(d["top_score_tied"].sum()),"top_score_near_ties_lt_002":int(d["top_score_near_tied"].sum()),
            "delisted_top_candidates":int(d["is_delisted"].eq(True).sum()),
            "top_candidates_with_isin":int(d["isin_present"].sum()),
            "top_score_median":float(d["top_score"].median()),"margin_median":float(d["margin"].median())}
    return d,report

def write_strength(out_dir:Path,detail:pd.DataFrame,report:dict):
    out_dir.mkdir(parents=True,exist_ok=True);detail.to_parquet(out_dir/"candidate_strength.parquet",index=False)
    (out_dir/"candidate_strength.json").write_text(json.dumps(report,indent=2,sort_keys=True))
