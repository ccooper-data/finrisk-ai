import pytest
from finrisk.identity.sec_13f_positional import ColumnBounds,parse_page_words,validate_page_population

B=ColumnBounds(10,100,300,430)
def words(cusip,name,desc,status="",y=100):
    out=[];x=10
    for t in [cusip[:6],cusip[6:8],cusip[8]]: out.append({"text":t,"x0":x,"x1":x+20,"top":y});x+=25
    out.append({"text":name,"x0":110,"x1":250,"top":y})
    out.append({"text":desc,"x0":310,"x1":390,"top":y})
    if status:out.append({"text":status,"x0":440,"x1":470,"top":y})
    return out

def test_positional_columns_preserve_issuer_and_description():
    d=parse_page_words(words("037833100","APPLE INC","COM"),B)
    assert d.loc[0,"issuer_name"]=="APPLE INC" and d.loc[0,"issuer_description"]=="COM"

def test_call_put_rows_are_excluded():
    assert parse_page_words(words("037833910","APPLE INC","CALL"),B).empty

def test_added_marker_and_status_are_retained():
    d=parse_page_words(words("037833100","*APPLE INC","COM","A"),B)
    assert bool(d.loc[0,"added_marker"]) and d.loc[0,"status"]=="A"

def test_page_furniture_and_invalid_tokens_are_ignored():
    furniture=[{"text":"Run Date:","x0":10,"x1":50,"top":20},{"text":"Page 1","x0":440,"x1":470,"top":20}]
    assert parse_page_words(furniture,B).empty

def test_row_floor_fails_closed():
    d=parse_page_words(words("037833100","APPLE INC","COM"),B)
    with pytest.raises(ValueError): validate_page_population(d,2)
