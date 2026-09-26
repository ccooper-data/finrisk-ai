import pandas as pd
from finrisk.identity.discovery_diagnostics import discovery_diagnostic

def test_diagnostic_reports_candidates_without_accepting_them():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[["ACME HOLDINGS INC"]],"first_filing":["2010-01-01"]})
    u=pd.DataFrame({"security_id":["A.US"],"security_name":["Acme Holdings"],"isin":["X"],"is_delisted":[True]})
    d,s=discovery_diagnostic(i,u,1,.45)
    assert s["with_candidates"]==1 and d.loc[0,"rank"]==1
    assert "decision" not in d.columns
