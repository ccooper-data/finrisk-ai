from finrisk.market.capabilities import ProviderCapabilities,assess_provider

def test_current_only_provider_blocked():
    c=ProviderCapabilities("x",False,False,False,False,True,True,False)
    assert not assess_provider(c)["eligible_for_historical_ablation"]

def test_historical_identity_and_provenance_can_be_eligible():
    c=ProviderCapabilities("x",True,False,True,False,True,True,True)
    assert assess_provider(c)["eligible_for_historical_ablation"]
