import pandas as pd
from finrisk.identity.sec_13f_official_list import parse_official_13f_text,measure_name_coverage

def test_parser_requires_fixed_width_and_valid_cusip():
    good="037833100 "+"APPLE INC".ljust(30)+"COM".ljust(27)+"   "
    bad="037833101 "+"APPLE INC".ljust(30)+"COM".ljust(27)+"   "
    d=parse_official_13f_text(good+"\n"+bad)
    assert d["cusip"].tolist()==["037833100"]

def test_coverage_is_discovery_only():
    hard=pd.DataFrame({"cik":["1"]})
    aliases=pd.DataFrame({"cik":["1"],"name":["APPLE INC"]})
    official=pd.DataFrame({"cusip":["037833100"],"issuer_name":["APPLE INC"],"issuer_description":["COM"],"status":[""]})
    d,r=measure_name_coverage(hard,aliases,official,.90)
    assert bool(d.loc[0,"candidate_hit"]) and bool(d.loc[0,"exact_normalized_name_hit"])
    assert "accepted" not in d.columns
