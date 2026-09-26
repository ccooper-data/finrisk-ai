from finrisk.ingestion.sec_historical_names import parse_cik_name_line

def test_sec_cik_name_trailing_colon():
    assert parse_cik_name_line("ACME CORP:123456:")==("0000123456","ACME CORP")

def test_sec_cik_name_preserves_internal_colon():
    assert parse_cik_name_line("ACME: HOLDINGS:42:")==("0000000042","ACME: HOLDINGS")
