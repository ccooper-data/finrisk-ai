import pandas as pd
from finrisk.identity.sec_tier_a_pilot_runner import run_tier_a_pilot

def test_runner_module_imports_and_empty_pilot_is_safe(tmp_path):
    t=pd.DataFrame({"cik":[],"top_security_id":[],"target_priority":[]})
    p=pd.DataFrame({"cik":[],"candidate_security_id":[],"filing_date":[],"accession":[]})
    r=run_tier_a_pilot(t,p,"ua",tmp_path)
    assert r["planned_accessions"]==0 and r["documents_fetched"]==0
