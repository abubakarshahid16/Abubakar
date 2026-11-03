"""Item 14c: the contractor copy never says an engineer must confirm or check anything. Invented rows only."""

from __future__ import annotations

import io
import re
import zipfile

import openpyxl

from app import contractor_scrub as scrub
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
        {**_row(), "comment_by": "Engineer", "page_section": "p.2 - Set pressure"},
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
        {**_row(), "crs_ref": "Engineer-001"},
        _row(
            comment="Please ask ENGINEERING reviewer. Eng. to confirm. Limit is 10 barg."
        ),
        _row(comment="Value 12 barg exceeds the limit."),
    ]
    meta = {
        "rulebook_v2_note": "Rulebook version 2. Not yet confirmed by an engineer.",
        "run_status_note": "Decided by the reviewing engineer.",
        "project": "Invented job",
    }
    seen = _whole_issue_copy_text(rows, meta)
    assert any("exceeds the limit" in s for s in seen)
    assert [s[:60] for s in seen if WORDS.search(s)] == []


def test_the_code_check_knows_the_abbreviation_and_the_engineering_reviewer():
    for text in ("Eng. to confirm", "ask ENGINEERING reviewer", "the engineer"):
        assert quality.engineer_words_in(text)
    assert not quality.engineer_words_in("Civil engineering standard 4.1")


FILE = "Engineer note - invented plant long long long file name.pdf"


def test_the_contractors_own_file_name_tag_and_title_are_left_verbatim(monkeypatch):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    rows = [
        {**_row(), "document_name": "Engineer note.pdf"},
        {**_row(comment="Limit 10 barg exceeded."), "document_name": FILE},
        {**_row(comment="Another value is off."), "page_section": "p.3 - Eng. tag E-1"},
    ]
    cells = _issue_cells(rows)
    for kept in ("Engineer note.pdf", FILE, "p.3 - Eng. tag E-1"):
        assert kept in cells  # the file name is never "reviewer note.pdf", never empty
    assert not any("reviewer note.pdf" in c for c in cells)
    ours = [c for c in cells if quality.engineer_words_in(c)]
    assert set(ours) <= {"Engineer note.pdf", FILE, "p.3 - Eng. tag E-1"}  # only theirs


def test_the_internal_run_notes_count_the_cells_that_still_name_the_engineer(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    rows = [{**_row(), "document_name": "Engineer note.pdf"}]
    meta = {"review_run_id": "run-1", "export_quality": True, "copy": "internal"}
    view = crs_export.build_crs_view(rows, meta)
    notes = [n for n in view["review_notes"] if n["note"] == quality.NOTE_LEFT]
    assert len(notes) == 1 and notes[0]["count"] >= 1
    assert "Engineer note.pdf" not in notes[0]["detail"]  # cell names, never the text
    clean = crs_export.build_crs_view([_row()], meta)
    assert quality.NOTE_LEFT not in [n["note"] for n in clean["review_notes"]]
    issue = crs_export.build_crs_view(rows, {**meta, "copy": "issue"})
    assert quality.NOTE_LEFT not in [n["note"] for n in issue["review_notes"]]


def test_the_residual_forms_are_in_the_word_check():
    for text in (
        "Engr to confirm",
        "engineering review needed",
        "Engineering to confirm",
    ):
        assert quality.engineer_words_in(text)


PHRASES = (
    "Engineer to check",
    "Eng. to confirm",
    "ENGINEER TO TICK",
    "Engineer to check which clauses apply",
)


def test_a_contractor_field_equal_to_a_phrase_we_write_never_puts_it_in_our_cells(
    monkeypatch,
):
    """The exemption is by column and row role, never by string equality: a reference, section or file name that
    reads like our Priority label stays in ITS column and does not unlock the same words in OUR cells."""
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    for phrase in PHRASES:
        row = {
            **_row(comment="Set pressure 12 barg is above the limit."),
            "document_name": phrase,
            "page_section": phrase,
            "standard_reference": phrase,
            "priority": 3,
        }
        data = crs_export.build_crs(
            [row], {"review_run_id": "run-1", "copy": "issue", "export_quality": True}
        )
        sheet = openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]
        header = next(
            r for r in sheet.iter_rows() if r[0].value == crs_export.HEADERS[0]
        )
        own = {c.column for c in header if c.value in scrub.OWN_COLUMNS}
        assert own  # the own columns are found by their header cells
        for line in sheet.iter_rows(min_row=header[0].row + 1):
            for cell in line:
                if isinstance(cell.value, str) and phrase in cell.value:
                    assert cell.column in own, (phrase, cell.coordinate)
        priority = next(c for c in header if c.value == "Priority")
        got = sheet.cell(row=header[0].row + 1, column=priority.column).value
        assert not quality.engineer_words_in(got), (phrase, got)


def test_every_string_field_of_a_row_is_counted_when_it_still_names_the_engineer(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_contractor_no_engineer_words_enabled", True)
    view = {
        "rows": [
            {
                "document_name": "Engineer note.pdf",
                "priority_label": "Engineer to check",
                "comment": "Value is off.",
            }
        ]
    }
    # an own field is theirs and kept; the Priority label is ours and the scrub cuts it, so only the own field counts
    assert scrub.left_over_cells(view) == ["document_name"]
