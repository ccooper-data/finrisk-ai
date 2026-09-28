from __future__ import annotations
import json,time
from pathlib import Path
import httpx,pandas as pd
from finrisk.identity.sec_tier_a_pilot import tier_a_pilot_plan,pilot_summary
from finrisk.identity.sec_accession_fetch import accession_base_url,fetch_accession_index,accession_documents
from finrisk.identity.sec_accession_documents import select_accession_documents,validate_selected_urls
from finrisk.identity.sec_document_fetch import fetch_document
from finrisk.identity.identifier_corroboration import extract_identifiers
from finrisk.identity.sec_identifier_context import contextualize_identifiers

def run_tier_a_pilot(targets:pd.DataFrame,plan:pd.DataFrame,user_agent:str,out_dir:Path)->dict:
    pilot=tier_a_pilot_plan(targets,plan)
    rows=[];docs_seen=0;docs_skipped_oversize=0;docs_failed=0
    headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"}
    with httpx.Client(headers=headers,timeout=60) as client:
        for _,p in pilot.iterrows():
            base=accession_base_url(p["cik"],p["accession"])
            index,index_ev=fetch_accession_index(p["cik"],p["accession"],user_agent,client)
            docs=accession_documents(index,base)
            selected=select_accession_documents(docs,None,8)
            validate_selected_urls(selected,base)
            for d in selected:
                try:
                    text,ev=fetch_document(d["url"],user_agent,base,client)
                except ValueError as exc:
                    if "exceeds" in str(exc):
                        docs_skipped_oversize+=1
                        continue
                    raise
                except httpx.HTTPError:
                    docs_failed+=1
                    continue
                docs_seen+=1
                ids=extract_identifiers(text)
                for kind,values in [("CUSIP",ids["cusips"]),("ISIN",ids["isins"])]:
                    ctx=contextualize_identifiers(text,values)
                    for _,x in ctx.iterrows():
                        rows.append({"cik":p["cik"],"accession":p["accession"],"filing_date":p["filing_date"],
                                     "candidate_security_id":p["candidate_security_id"],"filing_form":p.get("form"),"document_url":d["url"],
                                     "document_name":d.get("name"),"document_selection_reason":d.get("selection_reason"),
                                     "document_sha256":ev["sha256"],"identifier_type":kind,"identifier":x["identifier"],
                                     "identifier_context":x["context"],"identifier_match_start":x["match_start"],"identifier_match_end":x["match_end"],
                                     "security_context":x["security_context"],"common_equity_context":x["common_equity_context"],
                                     "review_status":"unreviewed"})
                time.sleep(.11)
            time.sleep(.11)
    evidence=pd.DataFrame(rows)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence.to_parquet(out_dir/"tier_a_identifier_evidence.parquet",index=False)
    report={**pilot_summary(pilot),"documents_fetched":docs_seen,"identifier_evidence_rows":len(evidence),
            "common_equity_rows":int(evidence["common_equity_context"].sum()) if len(evidence) else 0,
            "targets_with_identifier_evidence":int(evidence["cik"].nunique()) if len(evidence) else 0,
            "documents_skipped_oversize":docs_skipped_oversize,"documents_http_failed":docs_failed}
    (out_dir/"tier_a_identifier_pilot.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report
