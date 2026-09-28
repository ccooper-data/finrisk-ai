from finrisk.identity.sec_13f_case_diagnostics import rank_near_misses,exact_keys

def test_exact_key_remains_separate_from_near_miss():
    aliases=["Hercules Offshore Incorporated"]
    names=["HERCULES OFFSHORE INC","HERCULES CAPITAL INC"]
    assert exact_keys(aliases,names)==["HERCULES OFFSHORE INC"]
    assert rank_near_misses(aliases,names)[0]["official_key"]=="HERCULES OFFSHORE INC"

def test_near_miss_does_not_become_exact():
    aliases=["ACME HOLDINGS INC"]
    names=["ACME HOLDING CO"]
    assert exact_keys(aliases,names)==[]
    assert rank_near_misses(aliases,names)[0]["score"]>0
