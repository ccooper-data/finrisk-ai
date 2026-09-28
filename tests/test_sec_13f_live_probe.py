import pandas as pd,pytest
from types import SimpleNamespace
from finrisk.identity.sec_13f_live_probe import run_coverage_orchestration

def manifest(entries):
    return {"vintages":[{"vintage":v,"year":int(v[:4]),"quarter":int(v[-1]),"format":fmt,"url":f"https://sec/{v}.{fmt}","available_formats":[fmt]} for v,fmt in entries]}

def cases():
    return pd.DataFrame({"cik":["1"],"last_filing":[pd.Timestamp("2021-10-01")]})

def aliases():
    return pd.DataFrame({"cik":["1"],"name":["ACME HOLDINGS INCORPORATED"]})

def parser(source,content):
    names=["APPLE INC","MICROSOFT CORP","ACME HLDGS INC"]
    return pd.DataFrame({"issuer_name":names}),{"ok":True,"format":source.fmt}

def loader(source):return source.vintage.encode()

def test_end_to_end_consumes_manifest_dispatches_formats_and_emits_four_observations():
    m=manifest([("2021Q4","txt"),("2020Q4","txt"),("2019Q4","pdf"),("2018Q4","pdf")])
    r=run_coverage_orchestration(cases(),aliases(),m,loader,parser)
    assert r["observation_count"]==4
    assert r["exact_hit_observations"]==4
    assert {v["format"] for v in r["sources"].values()}=={"txt","pdf"}
    assert r["sources"]["2021Q4"]["url"]=="https://sec/2021Q4.txt"

def test_missing_vintage_fails_before_any_retrieval():
    calls=[]
    m=manifest([("2021Q4","txt")])
    with pytest.raises(ValueError,match="Unresolved 13F"):
        run_coverage_orchestration(cases(),aliases(),m,lambda s:calls.append(s) or b"x",parser)
    assert calls==[]

def test_positive_control_failure_voids_run():
    def bad_parser(source,content):
        return pd.DataFrame({"issuer_name":["APPLE INC","ACME HLDGS INC"]}),{"ok":True}
    m=manifest([("2021Q4","txt"),("2020Q4","txt"),("2019Q4","pdf"),("2018Q4","pdf")])
    with pytest.raises(ValueError,match="Positive control failure"):
        run_coverage_orchestration(cases(),aliases(),m,loader,bad_parser)

def test_source_metadata_is_from_resolved_manifest_not_template():
    m=manifest([("2021Q4","txt"),("2020Q4","txt"),("2019Q4","pdf"),("2018Q4","pdf")])
    r=run_coverage_orchestration(cases(),aliases(),m,loader,parser)
    assert all(x["url"].startswith("https://sec/") for x in r["sources"].values())
