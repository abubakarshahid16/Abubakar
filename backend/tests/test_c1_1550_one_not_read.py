"""#1550: with PAGE_READ_BY_READING_ENABLED every screen and CRS line counts
"not read" ONE way - no reading came back for the page (#1473), the count
the CRS footer and the issue gate use. A read page no datasheet field was
taken from is said as that, never "not read". Switch off: unchanged.

INVENTED documents only."""

from __future__ import annotations

import pytest

from app import (
    absence,
    ai_numbers,
    comparison,
    crs_mapping,
    export_status,
    page_ledger,
    page_not_read,
)
from app.config import settings
from tests.test_c1_1473_page_read import _prose_doc, temp_storage  # noqa: F401

#: A run stored with the switch on: page 2 had no reading, pages 1-3 no field.
ON = {
    "pages_total": 3,
    "fact_pages": [],
    "pages_not_read_into_fields": [1, 2, 3],
    "pages_read": [1, 3],
    "pages_not_read": [2],
    "pages_not_read_why": {
        "2": "excluded from the index on purpose (rule page_classified_toc)"
    },
}
#: The same run stored with the switch off.
OFF = {
    k: v
    for k, v in ON.items()
    if k not in ("pages_read", "pages_not_read", "pages_not_read_why")
}
READER = {"engine": "claude", "model": "m", "pages": 2, "pages_read": 2}


def test_readiness_strip_counts_the_reading_when_on(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    pages = page_ledger.readiness_pages(_prose_doc(ocr_pending=2))
    assert pages["unread_pages"] == [2]
    assert pages["pages_read"] == 2
    assert set(pages["unread_page_reasons"]) == {"2"}


def test_readiness_strip_unchanged_when_off(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", False)
    pages = page_ledger.readiness_pages(_prose_doc(ocr_pending=2))
    assert pages["unread_pages"] == [1, 2, 3]
    assert pages["pages_read"] == 0
    assert set(pages["unread_page_reasons"]) == {"1", "2", "3"}


def test_export_lines_say_not_read_not_into_fields_when_on():
    assert (
        export_status.unread_pages_line([2], by_reading=True)
        == "Unread pages: 1 page(s) not read (2)"
    )
    assert (
        export_status.unread_pages_line([2])
        == "Unread pages: 1 page(s) not read into fields (2)"
    )


def test_crs_header_counts_the_issue_gate_list_when_on():
    note = export_status.run_header_note("failed", {"page_coverage": ON}, [1, 2, 3], [])
    assert "Unread pages: 1 page(s) not read (2)" in note
    off = export_status.run_header_note("failed", {"page_coverage": OFF}, [1, 2, 3], [])
    assert "Unread pages: 3 page(s) not read into fields (1, 2, 3)" in off


def _lines(cov):
    parts = absence.unchecked_parts(
        run_status="completed", outcome={"page_coverage": cov}
    )
    return [p["line"] for p in parts]


def test_review_notes_not_read_is_the_reading_and_no_field_is_its_own_line():
    lines = _lines(ON)
    assert (
        "1 page(s) of this submittal were not read; values on them could not be checked."
        in lines
    )
    assert any(
        line.startswith("2 page(s) of this submittal were read, but no datasheet field")
        for line in lines
    )
    assert not any("not read into fields" in line for line in lines)


def test_review_notes_unchanged_when_off():
    assert _lines(OFF)[0] == (
        "3 page(s) of this submittal were not read into fields; "
        "values on them could not be checked."
    )
    assert not any("datasheet field" in line for line in _lines(OFF))


def test_reader_line_states_its_boundary_when_on():
    line = absence.reader_summary_line(READER, 3)
    assert line.startswith(
        "AI reader claude (m) read 2 of 2 page(s) it was given (3 page(s) in this submittal)"
    )
    assert (
        absence.reader_summary_line(READER)
        == "AI reader claude (m) read 2 of 2 page(s)."
    )
    steps = ai_numbers.for_run(
        {"page_coverage": ON, "requirement_split": {"reader": READER}}, None, None
    )
    assert "(2 given to it of 3 in this submittal)" in steps["reader"]["lines"][0]
    steps = ai_numbers.for_run(
        {"page_coverage": OFF, "requirement_split": {"reader": READER}}, None, None
    )
    assert "given to it" not in steps["reader"]["lines"][0]


def _unread_finding():
    return {
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "reason_code": "UNREAD_PAGES",
        "standard_name": "S",
        "contractor_page": 3,
    }


def test_crs_review_note_says_no_field_taken_when_on():
    notes = crs_mapping.build_review_notes(
        [_unread_finding()], [], [1, 2, 3], {"page_coverage": ON}
    )
    note = next(n for n in notes if n["count"] == 1)
    assert note["note"] == page_not_read.NOTE_NO_FIELD_PAGES
    # an unread page is never also counted as no field taken
    assert "page 2 was not read" in note["detail"]
    assert "pages 1, 3 had no datasheet field taken from them" in note["detail"]
    assert "not yet read" not in note["detail"]


def test_crs_review_note_on_only_unread_pages_is_not_called_no_field():
    cov = {**ON, "pages_not_read": [1, 2, 3]}
    notes = crs_mapping.build_review_notes(
        [_unread_finding()], [], [1, 2, 3], {"page_coverage": cov}
    )
    note = next(n for n in notes if n["count"] == 1)
    assert note["note"] == page_not_read.NOTE_PAGE_NOT_READ
    assert "no datasheet field" not in note["detail"]


def test_crs_review_note_unchanged_when_off():
    notes = crs_mapping.build_review_notes(
        [_unread_finding()], [], [1, 2, 3], {"page_coverage": OFF}
    )
    note = next(n for n in notes if n["count"] == 1)
    assert note["note"] == crs_mapping.NOTE_UNREAD_PAGES
    assert "are not yet read into fields" in note["detail"]


@pytest.mark.parametrize(
    "cov, words",
    [
        (
            ON,
            "page 2 was not read; pages 1, 3 had no datasheet field taken from them, "
            "so the value may be there",
        ),
        (OFF, "pages 1-3 were not read into fields, so the value may be there"),
    ],
)
def test_finding_rationale_words_follow_the_switch(cov, words):
    out = comparison.qualify_by_pages({"status": comparison.MISSING_INFORMATION}, cov)
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert words in out["rationale"]


#: The run's reading: pages 1-3 with no field, page 5 the AI reader did not finish.
READING = {"status": page_ledger.READING_INCOMPLETE, "incomplete_pages": [1, 2, 3, 5]}


@pytest.mark.parametrize(
    "cov, words",
    [
        (
            {**ON, "pages_total": 5, "reading": READING},
            "the reading is incomplete (page 2 not read; pages 1, 3 no datasheet field "
            "taken; page 5 not read in full, see the run's page coverage)",
        ),
        (
            {**OFF, "pages_total": 5, "reading": READING},
            "the reading is incomplete (pages 1-3, 5 not read in full, see the run's "
            "page coverage)",
        ),
    ],
)
def test_the_held_approval_words_follow_the_switch_and_the_hold_stays(cov, words):
    complete = {"sufficient": True, "fields_read": 240, "fields_estimated": 250}
    out = comparison.recommend_code(
        [{"compliance_status": comparison.COMPLIANT}], complete, page_coverage=cov
    )
    assert out["code"] == comparison.CODE_MANUAL
    assert out.get("reading_incomplete") is True
    assert words in out["reason"]


STORED = "Both readers found no field on this page, so it is not counted as read"
SAID = (
    "Both readers found no field on this page, so no datasheet field was taken from it"
)


def test_a_stored_reason_on_a_read_page_is_said_as_no_field_taken():
    """At render time only: the stored run is not rewritten."""
    cov = {
        **ON,
        "pages_ai_not_read": [1],
        "not_read_reasons": {"1": STORED, "2": STORED},
    }
    before = dict(cov["not_read_reasons"])
    reasons = page_ledger.run_unread_reasons(cov)
    assert reasons["1"] == SAID
    assert reasons["2"] == ON["pages_not_read_why"]["2"]
    assert cov["not_read_reasons"] == before


def test_a_stored_reason_is_unchanged_when_off():
    cov = {**OFF, "not_read_reasons": {"1": STORED}}
    assert page_ledger.run_unread_reasons(cov)["1"] == STORED


def test_the_no_field_part_states_its_boundary_against_the_clean_pages():
    """Two lists, two meanings: `pages_read_no_field` (both readers looked and
    found none; not held) is said apart from no field taken (value may be there)."""
    cov = {**ON, "pages_read_no_field": [4, 5]}
    line = next(
        ln
        for part, ln in page_not_read.unchecked_page_parts(cov)
        if part == "no_field_pages"
    )
    assert line.startswith(
        "2 page(s) of this submittal were read, but no datasheet field"
    )
    assert (
        "2 other page(s) were read by both readers and held no checklist field" in line
    )
    plain = next(
        ln
        for part, ln in page_not_read.unchecked_page_parts(ON)
        if part == "no_field_pages"
    )
    assert "other page(s)" not in plain
