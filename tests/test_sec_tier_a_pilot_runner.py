import pandas as pd
from finrisk.identity.sec_tier_a_pilot_runner import run_tier_a_pilot

def test_runner_module_imports_and_empty_pilot_is_safe(tmp_path):
    t=pd.DataFrame({"cik":[],"top_security_id":[],"target_priority":[]})
    p=pd.DataFrame({"cik":[],"candidate_security_id":[],"filing_date":[],"accession":[]})
    r=run_tier_a_pilot(t,p,"ua",tmp_path)
    assert r["planned_accessions"]==0 and r["documents_fetched"]==0


def test_runner_does_not_abort_entire_pilot_on_oversized_document(tmp_path,monkeypatch):
    import finrisk.identity.sec_tier_a_pilot_runner as m
    targets=pd.DataFrame({"cik":["1"],"top_security_id":["A.US"],"target_priority":["A_high_margin_isin"]})
    plan=pd.DataFrame({"cik":["1"],"candidate_security_id":["A.US"],"filing_date":["2010-01-01"],"accession":["x"]})
    monkeypatch.setattr(m,"fetch_accession_index",lambda *a,**k:({"directory":{"item":[{"name":"big.htm"},{"name":"small.htm"}]}},{}))
    monkeypatch.setattr(m,"accession_documents",lambda index,base:[{"name":"big.htm","url":base+"/big.htm"},{"name":"small.htm","url":base+"/small.htm"}])
    monkeypatch.setattr(m,"fetch_document",lambda url,*a,**k: (_ for _ in ()).throw(ValueError("SEC document exceeds 8000000 bytes")) if url.endswith("big.htm") else ("CUSIP 037833100 common stock",{"sha256":"x"}))
    r=m.run_tier_a_pilot(targets,plan,"ua",tmp_path)
    assert r["documents_skipped_oversize"]==1 and r["documents_fetched"]==1
