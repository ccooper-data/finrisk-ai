from finrisk.identity.sec_filing_names import filing_name_history

def test_filing_name_history_preserves_former_period():
    p={"name":"NEWCO","formerNames":[{"name":"OLDCO","from":"2001-01-01","to":"2010-01-01"}],
       "filings":{"recent":{"filingDate":["2011-01-01"],"accessionNumber":["x"]}}}
    d=filing_name_history(p,"42")
    old=d[d["sec_name"].eq("OLDCO")].iloc[0]
    assert old["from_date"]=="2001-01-01" and old["to_date"]=="2010-01-01"
