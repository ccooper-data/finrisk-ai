import pandas as pd

def test_ticker_map_contract_normalizes_cik_and_ticker():
    payload={"0":{"cik_str":320193,"ticker":"aapl","title":"Apple Inc."}}
    rows=[{"cik":str(x["cik_str"]).zfill(10),"ticker":str(x["ticker"]).upper(),"title":x["title"]} for x in payload.values()]
    df=pd.DataFrame(rows)
    assert df.loc[0,"cik"]=="0000320193"
    assert df.loc[0,"ticker"]=="AAPL"
