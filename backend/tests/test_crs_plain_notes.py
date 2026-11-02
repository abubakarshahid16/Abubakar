"""#1592 items d and e: the CRS notice names each part that could not be checked by what it
is, and the internal copy says in plain words why rows say ENGINEER TO TICK. Words only.
Invented data; the route is `test_review_screen`'s synthetic world."""

from __future__ import annotations

import io

import openpyxl
import pytest

from app import absence, access, crs_export, crs_mapping, db, main
from app.config import settings

OUTCOME = {
    "table_values_not_compared": [{"count": 89}, {"count": 1}],
    "requirements_held_back": {"text_quality": 1},
    "unchecked_counts": {"not_compared": 7, "not_applied": 3, "checked": 0},
}
SHARE = absence.share_sentence(7, 3, 0)


def _parts(**more):
    return absence.unchecked_parts(run_status="completed", outcome={**OUTCOME, **more})


def test_the_notice_names_each_part_by_what_it_is(monkeypatch):
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    parts = _parts()
    assert absence.notice_for(parts, internal=True) == (
        "REVIEW INCOMPLETE: 3 part(s) could not be checked - this sheet is not a complete"
        " review. Part 1: 90 standards-table value(s) were not compared: no matching field"
        " on this submittal. Part 2: 1 requirement(s) were held back: their text could not"
        f" be read reliably. Part 3: {SHARE}"
    )


def test_the_notice_never_prints_an_internal_id(monkeypatch):
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    parts = absence.unchecked_parts(
        run_status="failed",
        outcome={
            **OUTCOME,
            "partial": True,
            "datasheet_check_not_run": "the sheet could not be read",
            "standards_not_checked": ["INV-1"],
            "error": "stopped",
        },
        partial_findings=2,
        ai_status={"complete": False, "plain": "The AI check did not finish."},
        web_status={"complete": False, "plain": "The web check did not finish."},
    )
    notice = absence.notice_for(parts, internal=True)
    ids = {p["part"] for p in parts}
    assert len(ids) >= 6
    for part in ids:
        assert part not in notice
    counted = [p for p in parts if not p.get("detail")]
    assert notice.count("Part ") == len(counted)
    for p in counted:
        assert p["line"] in notice


def test_a_detail_line_is_not_a_part(monkeypatch):
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    parts = [
        {"part": "a", "line": "One thing."},
        {"part": "b", "line": "Why it is so.", "detail": True},
    ]
    notice = absence.notice_for(parts, internal=True)
    assert "1 part(s)" in notice and "Part 1: One thing." in notice
    assert "Why it is so." not in notice


def test_the_contractors_copy_has_the_count_and_the_share_not_the_parts(monkeypatch):
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    parts = _parts()
    notice = absence.notice_for(parts)
    assert "3 part(s)" in notice and SHARE in notice
    assert "Part 1" not in notice and "standards-table" not in notice


def test_switch_off_the_notice_is_as_before():
    assert settings.crs_plain_notes_enabled is False
    parts = _parts()
    want = (
        "REVIEW INCOMPLETE: 3 part(s) could not be checked - this sheet is not a complete"
        f" review. {SHARE}"
    )
    assert absence.notice_for(parts) == want
    assert absence.notice_for(parts, internal=True) == want
    assert absence.tick_note([{"row_kind": crs_mapping.ROW_KIND_SAFETY_TICK}]) is None


def _tick(**more):
    return {
        "row_kind": crs_mapping.ROW_KIND_SAFETY_TICK,
        "engineer_confirmed": False,
        **more,
    }


def test_the_tick_note_counts_the_open_rows_and_says_why(monkeypatch):
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    rows = [
        _tick(),
        _tick(),
        _tick(engineer_confirmed=True),
        {"row_kind": "datasheet_check", "engineer_confirmed": False},
    ]
    note = absence.tick_note(rows)
    assert note["note"] == absence.TICK_NOTE and note["count"] == 2
    detail = note["detail"]
    assert detail.startswith("2 rows of this sheet say ENGINEER TO TICK.")
    assert "safety field" in detail and "on purpose" in detail
    assert "does not count them as decided" in detail
    assert absence.tick_note([_tick()])["detail"].startswith(
        "1 row of this sheet says ENGINEER TO TICK."
    )
    assert absence.tick_note(rows[2:]) is None


def test_the_notice_row_is_tall_enough_only_with_the_switch(monkeypatch):
    meta = {"review_run_id": "r", "copy": "internal", "incomplete_notice": "x " * 500}
    row = {
        "document_name": "invented.pdf",
        "page_section": "p.1 - Invented",
        "comment": "Invented comment.",
        "comment_by": "AI Review",
        "row_kind": "datasheet_check",
    }

    def height():
        book = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs([row], meta)))
        return book.active.row_dimensions[crs_export.COLUMN_HEADER_ROW + 2].height

    assert height() == 30
    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    assert height() > 100


@pytest.fixture
def sheet_run(tmp_path, monkeypatch):
    """A run with one safety-tick finding: the row and the note, through the real path."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "notes.sqlite")
    monkeypatch.setattr(settings, "auth_mode", "disabled")
    db.reset_connection()
    db.init_db()
    from app import submittal_review

    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    now = "2026-11-02T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('sub','sub.pdf','s',1,'s','ready',1,?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at,"
            "outcome_json) VALUES ('r1','sub','completed',?,?,'{}')",
            (now, now),
        )
        conn.execute(
            "INSERT INTO review_findings (id,document_id,review_run_id,category,severity,"
            "requirement,finding,required_action,citation_ids,status,approval_status,"
            "created_at,updated_at,compliance_status,origin,show_for_engineer_tick,"
            "trust_label,tier,contractor_page,contractor_section,contractor_evidence_text,"
            "requirement_source_text,standard_clause) VALUES ('f1','sub','r1','c','low',"
            "'Invented rule.','f','a','[]','open','pending',?,?,'COMPLIANT','datasheet_check',"
            "1,'TESTED_CARD','SAFETY',1,'Invented field','7','Invented rule.','INV 1')",
            (now, now),
        )
    yield "r1"
    db.reset_connection()


def _content(run, copy):
    scope = access.AccessScope(user_id="t", allowed_document_ids=frozenset({"sub"}))
    return main._crs_content(run, scope, copy)


def test_the_tick_note_is_on_the_internal_copy_from_the_rows_on_it(
    sheet_run, monkeypatch
):
    rows, off, _n, _s = _content(sheet_run, "internal")
    assert [r["row_kind"] for r in rows] == [crs_mapping.ROW_KIND_SAFETY_TICK]
    assert not any(n["note"] == absence.TICK_NOTE for n in off["review_notes"])
    assert "ENGINEER TO TICK" not in off["incomplete_notice"]

    monkeypatch.setattr(settings, "crs_plain_notes_enabled", True)
    _rows, on, _n, _s = _content(sheet_run, "internal")
    [note] = [n for n in on["review_notes"] if n["note"] == absence.TICK_NOTE]
    assert note["count"] == 1
    assert note["detail"] in on["incomplete_notice"]
    book = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(_rows, on)))
    cells = [c for row in book["CRS"].iter_rows(values_only=True) for c in row if c]
    assert any(note["detail"] in str(c) for c in cells), "the sheet itself says it"
    # the row and the verdict do not change
    assert [r["comment"] for r in _rows] == [r["comment"] for r in rows]

    _rows, issue, _n, _s = _content(sheet_run, "issue")
    assert "ENGINEER TO TICK" not in issue["incomplete_notice"]
    assert not any(n["note"] == absence.TICK_NOTE for n in issue["review_notes"])
