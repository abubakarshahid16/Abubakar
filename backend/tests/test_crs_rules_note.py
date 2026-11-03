"""Item 14: ONE note at the top of the CRS, on both copies, only with the switch on. Invented rows only."""

from __future__ import annotations

import io

import openpyxl

from app import crs_export
from app import crs_export_quality as quality
from app.config import settings

ROWS = [
    {
        "document_name": "D.pdf",
        "page_section": "p.2",
        "comment": "c",
        "comment_by": "AI Review",
        "standard_reference": "S 1.1",
        "row_kind": "datasheet_check",
        "engineer_confirmed": True,
    }
]


def row_one(copy: str) -> str:
    data = crs_export.build_crs(ROWS, {"review_run_id": "run-1", "copy": copy})
    return openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]["A1"].value or ""


def test_the_note_is_one_sentence_on_row_1_of_both_copies_only_when_on(monkeypatch):
    for copy in ("internal", "issue"):
        monkeypatch.setattr(settings, "crs_rules_note_enabled", False)
        assert quality.RULES_NOTE not in row_one(copy)
        monkeypatch.setattr(settings, "crs_rules_note_enabled", True)
        assert row_one(copy).count(quality.RULES_NOTE) == 1


def test_the_note_says_drafts_checked_by_code_and_an_engineer_must_confirm():
    assert "drafts built from the standards and checked by code" in quality.RULES_NOTE
    assert "rows marked ✔ use an approved rule" in quality.RULES_NOTE
    assert quality.RULES_NOTE.endswith("An engineer must confirm this CRS.")


def test_the_note_keeps_the_run_status_line_first(monkeypatch):
    monkeypatch.setattr(settings, "crs_rules_note_enabled", True)
    said = quality.with_rules_note("REVIEW INCOMPLETE: run partial")
    assert said.startswith("REVIEW INCOMPLETE: run partial\n")
    assert said.endswith(quality.RULES_NOTE)
    monkeypatch.setattr(settings, "crs_rules_note_enabled", False)
    assert quality.with_rules_note("x") == "x"
    assert quality.with_rules_note(None) == ""
