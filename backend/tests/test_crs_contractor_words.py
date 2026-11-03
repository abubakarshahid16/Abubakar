"""Item 14c: the contractor copy never says an engineer must confirm or check anything. Invented rows only."""

from __future__ import annotations

import io
import re
import zipfile

import openpyxl

from app import crs_export
from app import crs_export_quality as quality
from app.config import settings

SAID = "Set pressure 12 barg is above the 10 barg limit. Engineer to confirm; ENGINEER TO TICK. Engineer to check"


def _row(comment=SAID, confirmed=True):
    return {
        "document_name": "D.pdf",
        "page_section": "p.2",
        "comment": comment,
        "comment_by": "AI Review",
        "standard_reference": "S 1.1",
        "row_kind": "datasheet_check",
        "engineer_confirmed": confirmed,
    }


def _cells(copy):
    data = crs_export.build_crs([_row()], {"review_run_id": "run-1", "copy": copy})
    book = openpyxl.load_workbook(io.BytesIO(data))
    return [
        str(c.value)
        for ws in book.worksheets
        for line in ws.iter_rows()
        for c in line
        if c.value is not None
    ]


def test_with_the_switch_on_no_cell_of_the_contractor_copy_names_the_engineer(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    cells = _cells("issue")
    assert any("above the 10 barg limit" in c for c in cells)
    assert [c for c in cells if quality.engineer_words_in(c)] == []


def test_the_internal_copy_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    assert any("ENGINEER TO TICK" in c for c in _cells("internal"))


def test_with_the_switch_off_the_contractor_copy_is_as_it_was(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", False)
    assert any("Engineer to confirm" in c for c in _cells("issue"))


def test_the_code_check_names_the_words_and_leaves_clean_text_alone():
    for text in ("Engineer to check", "ENGINEER TO TICK", "the engineer's note"):
        assert quality.engineer_words_in(text)
    assert not quality.engineer_words_in("Set pressure is above the limit.")
    assert not quality.engineer_words_in(None)


def test_only_the_parts_that_name_the_engineer_are_cut(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    out = quality.contractor_words({"comment": SAID})["comment"]
    assert out == "Set pressure 12 barg is above the 10 barg limit."
    clean = {"comment": "Value 12 barg; limit 10 barg."}
    assert quality.contractor_words(clean) is clean


def _issue_cells(rows):
    data = crs_export.build_crs(rows, {"review_run_id": "run-1", "copy": "issue"})
    book = openpyxl.load_workbook(io.BytesIO(data))
    return [
        str(c.value)
        for ws in book.worksheets
        for line in ws.iter_rows()
        for c in line
        if c.value is not None
    ]


def test_a_request_to_the_engineer_keeps_its_ask_in_contractor_words(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    out = quality.contractor_words(
        {"comment": "Clarification required from the Engineer."}
    )["comment"]
    assert out == "Clarification required."


def test_a_comment_that_is_all_engineer_wording_is_withheld_never_issued_as_an_instruction(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    only = _row(comment="Engineer to confirm. ENGINEER TO TICK.")
    kept = _row(comment="Set pressure 12 barg is above the 10 barg limit.")
    cells = _issue_cells([only, kept])
    view = crs_export.build_crs_view(
        [only, kept], {"review_run_id": "run-1", "copy": "issue"}
    )
    assert (
        len(view["rows"]) == 1
    )  # the all-engineer comment's row is withheld, not issued blank
    assert any("above the 10 barg limit" in c for c in cells)
    assert not any("An engineer must write it" in c for c in cells)
    assert not any("Engineer to confirm" in c for c in cells)


def test_no_cell_of_the_whole_contractor_copy_names_the_engineer(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    rows = [
        {**_row(), "comment_by": "Engineer", "page_section": "p.2 - engineer note"},
        _row(comment="Engineer to confirm."),
        _row(comment="Clarification required from the Engineer."),
    ]
    cells = _issue_cells(rows)
    assert [c for c in cells if quality.engineer_words_in(c)] == []


WORDS = re.compile(
    r"\bengineers?\b|\bengineering\s+reviewers?\b|\beng\.", re.IGNORECASE
)


def _whole_issue_copy_text(rows, meta):
    """Every string the issue file holds: each cell of each sheet, sheet names, document properties, and the raw text of
    every part of the zip (shared strings, properties) so nothing a reader can open is missed."""
    full = {"review_run_id": "run-1", "copy": "issue", **meta}
    data = crs_export.build_crs(rows, full)
    book = openpyxl.load_workbook(io.BytesIO(data))
    seen = [ws.title for ws in book.worksheets]
    for ws in book.worksheets:
        seen += [
            str(c.value) for line in ws.iter_rows() for c in line if c.value is not None
        ]
    seen += [str(v) for v in vars(book.properties).values() if isinstance(v, str)]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                seen.append(z.read(name).decode("utf-8", "replace"))
    return seen


def test_no_string_of_the_whole_issue_copy_names_the_engineer(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    rows = [
        {**_row(), "document_name": "Eng. note.pdf", "crs_ref": "Engineer-001"},
        _row(
            comment="Please ask ENGINEERING reviewer. Eng. to confirm. Limit is 10 barg."
        ),
        _row(comment="Value 12 barg exceeds the limit."),
    ]
    meta = {
        "rulebook_v2_note": "Rulebook version 2. Not yet confirmed by an engineer.",
        "run_status_note": "Decided by the reviewing engineer.",
        "project": "Invented job - Engineer to review",
    }
    seen = _whole_issue_copy_text(rows, meta)
    assert any("exceeds the limit" in s for s in seen)
    assert [s[:60] for s in seen if WORDS.search(s)] == []


def test_the_code_check_knows_the_abbreviation_and_the_engineering_reviewer():
    for text in ("Eng. to confirm", "ask ENGINEERING reviewer", "the engineer"):
        assert quality.engineer_words_in(text)
    assert not quality.engineer_words_in("Civil engineering standard 4.1")
