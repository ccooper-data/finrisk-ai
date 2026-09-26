from finrisk.market.scorecard import provider_scorecard

def test_failed_probe_blocks_full_ingestion():
    c={"eligible_for_historical_ablation":True,"warnings":[]};r={"public_demo_allowed":True}
    p={"passed":False,"reasons":["hard cases missing"]}
    assert not provider_scorecard(c,r,p)["eligible_for_full_ingestion"]

def test_capable_provider_without_probe_can_be_candidate():
    c={"eligible_for_historical_ablation":True,"warnings":[]};r={"public_demo_allowed":True}
    assert provider_scorecard(c,r)["eligible_for_full_ingestion"]
