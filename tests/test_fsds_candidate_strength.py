import pandas as pd
from finrisk.identity.fsds_candidate_strength import candidate_strength

def test_strength_reports_margin_and_preserves_normalized_identifier():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[[]],"first_filing":["2010-01-01"]})
    f=pd.DataFrame({"cik":["0000000001"],"name":["ACME HOLDINGS INC"]})
    u=pd.DataFrame({"security_id":["A.US","B.US"],"security_name":["Acme Holdings","Acme Holdings Preferred"],
                    "isin":[" us0378331005 ",None],"is_delisted":[True,True]})
    d,r=candidate_strength(i,f,u,.45,1)
    assert r["with_candidate"]==1
    assert bool(d.loc[0,"isin_present"])
    assert d.loc[0,"isin"]=="US0378331005"
    assert d.loc[0,"margin"] is not None


def test_strength_marks_tied_top_candidates_as_ambiguous():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[[]],"first_filing":["2010-01-01"]})
    f=pd.DataFrame({"cik":["0000000001"],"name":["ACME HOLDINGS INC"]})
    u=pd.DataFrame({"security_id":["A.US","B.US"],"security_name":["Acme Holdings","Acme Holdings"],
                    "isin":["US0378331005","US5949181045"],"is_delisted":[True,True]})
    d,r=candidate_strength(i,f,u,.45,1)
    assert bool(d.loc[0,"top_score_tied"])
    assert bool(d.loc[0,"top_score_near_tied"])
    assert r["top_score_ties"]==1


def test_strength_preserves_tied_candidate_set_for_diagnosis():
    i=pd.DataFrame({"cik":["1"],"distress_observations":[1],"has_current_ticker":[False],
                    "historical_names":[[]],"first_filing":["2010-01-01"]})
    f=pd.DataFrame({"cik":["0000000001"],"name":["ACME HOLDINGS INC"]})
    u=pd.DataFrame({"security_id":["A.US","B.US"],"security_name":["Acme Holdings","Acme Holdings"],
                    "isin":["US0378331005","US5949181045"],"is_delisted":[True,True]})
    d,_=candidate_strength(i,f,u,.45,1)
    assert d.loc[0,"top_tied_candidate_count"]==2
    assert d.loc[0,"top_tied_security_ids"]==["A.US","B.US"]
    assert d.loc[0,"top_tied_isins"]==["US0378331005","US5949181045"]
