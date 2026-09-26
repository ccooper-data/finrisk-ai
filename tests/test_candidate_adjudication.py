import pandas as pd
from finrisk.identity.adjudication import adjudication_queue

def test_close_candidates_are_not_high_priority():
    c=pd.DataFrame({"cik":["1","1"],"security_id":["a","b"],"discovery_score":[.95,.93]})
    q=adjudication_queue(c)
    assert q.loc[0,"review_priority"]!="high" and q.loc[0,"acceptance_status"]=="unreviewed"
