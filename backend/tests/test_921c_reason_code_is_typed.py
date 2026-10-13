"""#921 point 3 (PF2): what reaches the CRS follows a stored reason CODE, not
the first words of `ai_rationale`. A reworded sentence cannot move a finding
into or out of the CRS; a row from before the column still works.

Invented findings only."""
from __future__ import annotations

import pytest

from app import comparison, crs_mapping, db, review
from app.config import settings


def _f(status, rationale, **more):
    return {"id": "f1", "compliance_status": status, "ai_rationale": rationale, "origin": None,
            "requirement_source_text": "x", "standard_document_id": "d", **more}


def test_the_stored_code_decides_whatever_the_words_say():
    reworded = _f("NEEDS_ENGINEER_REVIEW", "Some pages were not read yet.", reason_code="UNREAD_PAGES")
    assert crs_mapping._unread(reworded) is True
    other = _f("NEEDS_ENGINEER_REVIEW", "UNREAD_PAGES: looks like it, but the code says otherwise",
               reason_code="PAGE_READER_ONLY")
    assert crs_mapping._unread(other) is False and crs_mapping._page_reader_only(other) is True


def test_a_row_from_before_the_column_is_read_by_its_words_once_in_one_place():
    old = _f("NEEDS_ENGINEER_REVIEW", "UNREAD_PAGES: pages 3-4 were not read", reason_code=None)
    assert crs_mapping._reason(old) == "UNREAD_PAGES" and crs_mapping._unread(old)
    assert crs_mapping._reason(_f("COMPLIANT", "fine", reason_code=None)) is None


@pytest.mark.parametrize("rationale, code", [
    ("requires_other_document: a certificate", comparison.REQUIRES_OTHER_DOCUMENT),
    ("no_field_matched: nothing paired", comparison.NO_FIELD_MATCHED),
    ("condition_not_met: not a vessel", comparison.CONDITION_NOT_MET),
    ("UNREAD_PAGES: 3", "UNREAD_PAGES"),
    ("PAGE_READER_ONLY: 3", "PAGE_READER_ONLY"),
    ("the value is 3 mm", None), ("", None), (None, None),
])
def test_the_code_is_derived_where_the_words_are_written(rationale, code):
    assert comparison.reason_code_of(rationale) == code


def test_the_code_is_stored_on_the_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "r.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema()
    try:
        cols = {r[1] for r in db.connect().execute("PRAGMA table_info(review_findings)")}
        assert "reason_code" in cols
    finally:
        db.reset_connection()


def test_the_crs_notes_follow_the_code():
    findings = [_f("NOT_IN_DOCUMENT_SCOPE", "reworded entirely", reason_code="requires_other_document",
                   standard_name="STD-1")]
    notes = crs_mapping.build_review_notes(findings, [], unread_pages=[])
    assert any(n["note"] == crs_mapping.NOTE_OTHER_DOCUMENT and n["count"] == 1 for n in notes)
