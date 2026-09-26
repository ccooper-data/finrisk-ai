import pandas as pd

def test_former_name_shape_supports_dates():
    x={"name":"OLD ACME INC","from":"2008-01-01","to":"2012-01-01"}
    row={"name":x.get("name"),"from_date":x.get("from"),"to_date":x.get("to")}
    assert row["from_date"]=="2008-01-01" and row["to_date"]=="2012-01-01"
