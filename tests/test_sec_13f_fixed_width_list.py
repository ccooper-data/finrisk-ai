from __future__ import annotations
import pytest
from finrisk.identity.sec_13f_official_list import (
    TEXT_LINE_WIDTH, parse_official_13f_fixed_width, text_list_fidelity,
    assert_text_list_fidelity, list_membership_events,
)

def _line(cusip, marker, name, description, status="", type_code="E"):
    line = (cusip + marker + name.ljust(28) + "  " + description.ljust(27))[:70]
    line = line.ljust(67)[:67] + status.ljust(3)
    return line.ljust(79)[:79] + type_code

# Real rows from 13flist2024q1.txt.
LINES = [
    _line("B38564108", "*", "EURONAV NV", "SHS", type_code="N"),
    _line("C00948122", " ", "AGRIFORCE GROWING SYSTEMS LT", "COM NEW"),
    _line("G00350101", " ", "LOBO EV TECHNOLOGIES LTD", "SHS", status="*A*"),
    _line("G0131Y100", " ", "AGRICULTURE & NAT SOL ACQ CO", "SHS CL A", status="*D*"),
]
TEXT = "\n".join(LINES) + "\n"

def test_every_line_is_eighty_columns():
    assert {len(l) for l in LINES} == {TEXT_LINE_WIDTH}

def test_fields_are_split_at_the_fixed_offsets():
    frame = parse_official_13f_fixed_width(TEXT)
    euronav = frame.iloc[0]
    assert euronav["cusip"] == "B38564108"
    assert euronav["issuer_name"] == "EURONAV NV"
    assert euronav["issuer_description"] == "SHS"
    assert euronav["marker"] == "*"
    assert euronav["type_code"] == "N"

def test_marker_column_is_independent_of_status_column():
    frame = parse_official_13f_fixed_width(TEXT)
    euronav = frame[frame["cusip"].eq("B38564108")].iloc[0]
    assert euronav["marker"] == "*"
    assert euronav["status"] == ""
    lobo = frame[frame["cusip"].eq("G00350101")].iloc[0]
    assert lobo["marker"] == ""
    assert lobo["status"] == "*A*"

def test_status_maps_to_list_membership_not_listing_status():
    frame = parse_official_13f_fixed_width(TEXT)
    assert bool(frame[frame["cusip"].eq("G00350101")].iloc[0]["added_to_13f_list"])
    assert bool(frame[frame["cusip"].eq("G0131Y100")].iloc[0]["deleted_from_13f_list"])

def test_membership_events_are_named_for_the_evidence_not_for_delisting():
    events = list_membership_events(parse_official_13f_fixed_width(TEXT), "2024Q1")
    assert set(events.columns) == {
        "cusip", "issuer_name", "issuer_description", "event",
        "added_to_13f_list_quarter", "deleted_from_13f_list_quarter",
    }
    assert "delist_date" not in events.columns
    deleted = events[events["event"].eq("deleted_from_13f_list")].iloc[0]
    assert deleted["deleted_from_13f_list_quarter"] == "2024Q1"
    assert deleted["added_to_13f_list_quarter"] is None

def test_fidelity_is_measured_before_filtering():
    report = text_list_fidelity(TEXT)
    assert report["distinct_widths"] == [TEXT_LINE_WIDTH]
    assert report["candidate_rows"] == 4
    assert report["cusip_valid_rate"] == 1.0
    assert_text_list_fidelity(report, "2024Q1", min_rows=4)

def test_a_format_change_fails_closed_instead_of_reading_as_low_coverage():
    shifted = "\n".join(l[:-1] for l in LINES)
    with pytest.raises(ValueError, match="Unexpected TXT line widths"):
        assert_text_list_fidelity(text_list_fidelity(shifted), "2024Q1", min_rows=1)

def test_invalid_cusip_rows_fail_the_assertion_rather_than_being_dropped_silently():
    corrupted = LINES[:3] + [_line("G0131Y101", " ", "AGRICULTURE & NAT SOL ACQ CO", "SHS CL A")]
    report = text_list_fidelity("\n".join(corrupted))
    assert report["cusip_valid_rate"] < 1.0
    with pytest.raises(ValueError, match="CUSIP validity below 100%"):
        assert_text_list_fidelity(report, "2024Q1", min_rows=1)
