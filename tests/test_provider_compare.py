from finrisk.market.provider_compare import compare_provider,rank_for_probe
from finrisk.market.capabilities import ProviderCapabilities
from finrisk.market.licensing import DataUsageRights

def test_ineligible_provider_excluded_from_probe_order():
    bad=ProviderCapabilities("bad",False,False,False,False,True,True,False)
    rights=DataUsageRights("bad",True,False,False,True,False)
    assert rank_for_probe([compare_provider(bad,rights)])==[]

def test_eligible_provider_can_enter_probe_order():
    good=ProviderCapabilities("good",True,True,True,True,True,True,True)
    rights=DataUsageRights("good",True,False,True,True,True)
    assert rank_for_probe([compare_provider(good,rights)])[0]["provider"]=="good"
