from finrisk.identity.sec_identifier_context import context_window,classify_identifier_context

def test_common_stock_context_is_distinct_from_notes():
    assert classify_identifier_context("CUSIP 123456789 common stock")["security_context"]=="common_equity"
    assert classify_identifier_context("CUSIP 123456789 7.5% senior notes due 2030")["security_context"]=="debt"

def test_preferred_is_not_common_equity():
    assert classify_identifier_context("CUSIP 123456789 Series A preferred stock")["security_context"]=="preferred"

def test_context_window_is_local_to_identifier():
    t="x"*500+"CUSIP 123456789 common stock"+"y"*500
    w=context_window(t,"123456789",100)
    assert len(w)<250 and "common stock" in w
