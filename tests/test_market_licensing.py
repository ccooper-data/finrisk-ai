from finrisk.market.licensing import DataUsageRights,publication_gate

def test_nonredistributable_raw_data_remains_private():
    r=DataUsageRights("x",True,False,True,True,True)
    g=publication_gate(r)
    assert g["public_demo_allowed"] and not g["raw_artifact_publishable"]

def test_provider_without_demo_rights_blocked():
    r=DataUsageRights("x",True,False,False,False,False)
    assert not publication_gate(r)["public_demo_allowed"]
