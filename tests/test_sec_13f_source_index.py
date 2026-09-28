from __future__ import annotations
import pytest
from finrisk.identity.sec_13f_source_index import (
    build_manifest, parse_source_index, preferred_source, resolve,
    missing_quarters, preflight, assert_preflight,
)

# Mirrors the real index page: old /divisions path, the 2021Q2 move to /files,
# TXT alongside PDF from 2020, a "-txt" infix filename, and a missing quarter.
INDEX_HTML = """
<a href="/divisions/investment/13f/13flist1997q3.pdf">1997 Q3</a>
<a href="/divisions/investment/13f/13flist2009q4.pdf">2009 Q4</a>
<a href="/divisions/investment/13f/13flist2020q1.pdf">2020 Q1 PDF</a>
<a href="/files/investment/13flist2020q1.txt">2020 Q1 TXT</a>
<a href="/divisions/investment/13f/13flist2021q1.pdf">2021 Q1</a>
<a href="/files/investment/13flist2021q2.pdf">2021 Q2 PDF</a>
<a href="/files/investment/13flist2021q2.txt">2021 Q2 TXT</a>
<a href="/files/investment/13flist2025q3-txt.txt">2025 Q3 TXT</a>
<a href="/divisions/investment/13f-list.pdf">current list</a>
"""

def test_parses_both_path_layouts():
    index = parse_source_index(INDEX_HTML)
    assert index["2009Q4"]["pdf"].endswith("/divisions/investment/13f/13flist2009q4.pdf")
    assert index["2021Q2"]["pdf"].endswith("/files/investment/13flist2021q2.pdf")

def test_ignores_the_unvintaged_current_list():
    assert all(v[0].isdigit() for v in parse_source_index(INDEX_HTML))

def test_handles_the_txt_infix_filename():
    assert parse_source_index(INDEX_HTML)["2025Q3"]["txt"].endswith("13flist2025q3-txt.txt")

def test_txt_is_preferred_over_pdf_when_both_exist():
    assert preferred_source({"pdf": "p", "txt": "t"}) == ("txt", "t")
    assert preferred_source({"pdf": "p"}) == ("pdf", "p")
    assert preferred_source({}) is None

def test_manifest_records_available_formats_and_choice():
    entry = next(e for e in build_manifest(INDEX_HTML)["vintages"] if e["vintage"] == "2020Q1")
    assert entry["format"] == "txt"
    assert entry["available_formats"] == ["pdf", "txt"]

def test_resolve_returns_format_and_url():
    source = resolve(build_manifest(INDEX_HTML), "2009q4")
    assert (source.fmt, source.year, source.quarter) == ("pdf", 2009, 4)

def test_unpublished_vintage_raises_rather_than_guessing_a_url():
    with pytest.raises(KeyError, match="not published"):
        resolve(build_manifest(INDEX_HTML), "1997Q4")

def test_missing_quarters_are_reported_as_genuinely_absent():
    gaps = missing_quarters(build_manifest(INDEX_HTML), "1997Q3", "2009Q4")
    assert "1997Q4" in gaps and "1997Q3" not in gaps and "2009Q4" not in gaps

def test_preflight_fails_before_retrieval_when_a_vintage_is_unresolved():
    manifest = build_manifest(INDEX_HTML)
    ok = preflight(manifest, ["2009Q4", "2021Q2"])
    assert ok["all_resolved"]
    assert_preflight(ok)

    bad = preflight(manifest, ["2009Q4", "2021Q4"])
    assert bad["unavailable"] == ["2021Q4"]
    with pytest.raises(ValueError, match="Unresolved 13F list vintages"):
        assert_preflight(bad)
