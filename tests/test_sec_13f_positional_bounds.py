from __future__ import annotations
import pytest
from finrisk.identity.sec_13f_positional import (
    ColumnBounds, OFFICIAL_LIST_BOUNDS, parse_page_words,
    page_fidelity_report, assert_equity_cusip_fidelity,
)

def _word(text, x0, top):
    return {"text": text, "x0": x0, "x1": x0 + 6.0 * len(text), "top": top}

def _row(cusip, name_words, description, top, status="", flag=""):
    root, issue, check = cusip[:6], cusip[6:8], cusip[8]
    words = [_word(root, 72.84, top), _word(issue, 115.71, top), _word(check, 135.14, top)]
    if flag:
        words.append(_word(flag, 150.14, top))
    x = 167.40
    for w in name_words:
        words.append(_word(w, x, top))
        x += 6.0 * len(w) + 8.0
    words.append(_word(description, 350.50, top))
    if status:
        words.append(_word(status, 468.24, top))
    return words

# Real geometry observed in 13flist2009q4.pdf.
PAGE = (
    _row("G0585R106", ["ASSURED", "GUARANTY", "LTD"], "COM", 136.7, flag="*")
    + _row("G0585R906", ["ASSURED", "GUARANTY", "LTD"], "CALL", 153.8)
    + _row("G0585R956", ["ASSURED", "GUARANTY", "LTD"], "PUT", 171.0)
    + _row("G06750106", ["AUTOCHINA", "INTERNATIONAL", "LIMI"], "SHS", 188.2, status="ADDED")
    + _row("G0692U109", ["AXIS", "CAPITAL", "HOLDINGS"], "SHS", 239.8, flag="*")
)

def test_verified_bounds_parse_equity_rows():
    frame = parse_page_words(PAGE, OFFICIAL_LIST_BOUNDS)
    assert list(frame["cusip"]) == ["G0585R106", "G06750106", "G0692U109"]
    assert frame.iloc[0]["issuer_name"] == "ASSURED GUARANTY LTD"
    assert bool(frame.iloc[0]["added_marker"]) is True
    assert bool(frame.iloc[1]["added_marker"]) is False

def test_status_column_is_not_absorbed_into_description():
    frame = parse_page_words(PAGE, OFFICIAL_LIST_BOUNDS)
    autochina = frame[frame["cusip"].eq("G06750106")].iloc[0]
    assert autochina["issuer_description"] == "SHS"
    assert autochina["status"] == "ADDED"

def test_call_and_put_rows_are_dropped():
    frame = parse_page_words(PAGE, OFFICIAL_LIST_BOUNDS)
    assert not frame["issuer_description"].str.upper().isin({"CALL", "PUT"}).any()

def test_regression_previous_bounds_clipped_the_cusip_issue_field():
    """ColumnBounds(35,115,330,500) cut the issue-number word at x0=115.7 by
    0.7pt, leaving a 6-character CUSIP that can never validate -> zero rows."""
    frame = parse_page_words(PAGE, ColumnBounds(35, 115, 330, 500))
    assert frame.empty

def test_fidelity_report_counts_pre_filter_population():
    report = page_fidelity_report(PAGE, OFFICIAL_LIST_BOUNDS)
    assert report["candidate_rows"] == 5
    assert report["option_rows"] == 2
    assert report["equity_rows"] == 3
    assert report["equity_valid_rate"] == 1.0
    assert_equity_cusip_fidelity(report, "2009Q4")

def test_fidelity_report_exposes_a_bad_bounds_guess_as_empty_not_valid():
    report = page_fidelity_report(PAGE, ColumnBounds(35, 115, 330, 500))
    assert report["candidate_rows"] == 0
    with pytest.raises(ValueError, match="No equity rows parsed"):
        assert_equity_cusip_fidelity(report, "2009Q4")

def test_option_pseudo_cusips_fail_the_check_digit():
    from finrisk.identity.identifier_corroboration import valid_cusip
    assert valid_cusip("G0585R106")
    assert not valid_cusip("G0585R906")
    assert not valid_cusip("G0585R956")
