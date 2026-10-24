from finrisk.market.probe_gate import provider_probe_gate

def test_provider_fails_when_hard_distress_cases_missing():
    r={"priced_rate":.9,"by_group":{"distressed_no_current_ticker":{"companies":50,"resolved":20,"priced":10}}}
    assert not provider_probe_gate(r)["passed"]

def test_provider_can_pass_strong_probe():
    r={"priced_rate":.9,"by_group":{"distressed_no_current_ticker":{"companies":50,"resolved":45,"priced":40}}}
    assert provider_probe_gate(r)["passed"]
