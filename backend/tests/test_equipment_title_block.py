"""Owner decision 1 Nov (part of #1478): ONLY the title block sets the equipment type; a panel
heading in the page body ("MOTOR DATA") never does. None or two types in the title block: the
type is NULL, marked 'engineer to confirm', and the review says so. Invented pages only."""

from __future__ import annotations

import json

import pytest

from app import (
    classification,
    db,
    equipment_title_block,
    form_reader_run,
    submittal_fill,
)
from app.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _page(title_lines, *, panel="MOTOR DATA"):
    """A title block of `title_lines`, a body (the panel label sits at line 11, beyond the
    page edge), and a footer."""
    body = (
        [f"Process line {i}" for i in range(5)]
        + [panel]
        + [f"Value line {i}" for i in range(6)]
    )
    return "\n".join(
        [*title_lines, *body, "Notes", "Page 1 of 3", "Rev 0", "Issued", "End"]
    )


def _doc(doc_id, text, *, confirmed=False):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (doc_id, f"{doc_id}.pdf", doc_id, 1, "x", "ready", "2026-11-01"),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
            " VALUES (?,?,?,?,0)",
            (doc_id, 1, text, len(text)),
        )
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
            " text, token_count, content_hash, retrievable) VALUES (?,?,?,?,?,?,?,1,?,1)",
            (f"{doc_id}_c", doc_id, "f", 1, 1, 1, text, doc_id),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, document_role,"
            " confirmed_by) VALUES (?,?,?,?)",
            (doc_id, "t", "CONTRACTOR_SUBMITTAL", None),
        )
        if confirmed:
            conn.execute(
                "INSERT INTO users (id, email, display_name, password_hash, created_at)"
                " VALUES ('u1','u@x.test','u','x','2026-11-01')"
            )
            conn.execute(
                "UPDATE document_classification SET confirmed_by='u1', equipment_type='Valve'"
                " WHERE document_id=?",
                (doc_id,),
            )


def _row(doc_id):
    return (
        db.connect()
        .execute(
            "SELECT equipment_type, equipment_type_evidence FROM document_classification"
            " WHERE document_id=?",
            (doc_id,),
        )
        .fetchone()
    )


def _run(doc_id):
    classification.classify_equipment_type_for_submittal(doc_id)
    submittal_fill.fill(doc_id)
    return _row(doc_id)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", True)


@pytest.mark.parametrize("switch", [True, False])
def test_the_title_block_names_a_pump_and_a_motor_panel_in_the_body_is_ignored(
    monkeypatch, switch
):
    """The pump comes from the title block in both modes; the same sheet without the
    pump title line becomes a Motor from its panel only with the switch off."""
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", switch)
    _doc(
        "d1",
        _page(
            ["ACME PROJECT", "CENTRIFUGAL PUMP DATA SHEET", "Doc 1", "Rev 0", "Tag P-1"]
        ),
    )
    _doc("d2", _page(["ACME PROJECT", "Doc 1", "Rev 0", "Tag P-1", "Sheet 1"]))
    row = _run("d1")
    assert row["equipment_type"] == "Centrifugal Pump"
    assert json.loads(row["equipment_type_evidence"])["method"] == "title_phrase_match"
    assert _run("d2")["equipment_type"] == (None if switch else "Motor")


def test_a_reference_line_citing_a_motor_specification_is_not_a_second_type(on):
    _doc(
        "d1",
        _page(
            [
                "CENTRIFUGAL PUMP DATA SHEET",
                "Ref. specification: Electric Motors",
                "Doc 1",
                "Rev 0",
                "Tag P-1",
            ]
        ),
    )
    assert _run("d1")["equipment_type"] == "Centrifugal Pump"


@pytest.mark.parametrize(
    "second",
    ["APPLICABLE TO: COMPRESSOR DATA SHEET", "PUMP / MOTOR DATA SHEET per API 610"],
)
def test_a_reference_word_line_naming_another_data_sheet_is_still_a_second_type(
    on, second
):
    """#1552: a reference word drops a line only when it cites a document; a line
    naming another equipment's data sheet is a second type of this title block."""
    _doc("d1", _page(["CENTRIFUGAL PUMP DATA SHEET", second, "Doc 1", "Rev 0", "x"]))
    row = _run("d1")
    assert row["equipment_type"] is None
    assert json.loads(row["equipment_type_evidence"])["reason"] == "ambiguous"


@pytest.mark.parametrize("switch", [True, False])
def test_the_form_reader_takes_no_type_from_the_body_with_the_switch_on(
    monkeypatch, switch
):
    """A NULL type (engineer to confirm) stays None for the form reader: a body
    panel naming equipment never picks that type's field list."""
    monkeypatch.setattr(settings, "equipment_from_title_block_enabled", switch)
    text = _page(
        ["ACME PROJECT", "TECHNICAL DATA", "Doc 1", "Rev 0", "Tag X-1"],
        panel="CENTRIFUGAL PUMP DATA",
    )
    _doc("d1", text)
    chunks = [{"page_start": 1, "ordinal": 1, "text": text}]
    got = form_reader_run.equipment_type_of("d1", chunks)
    assert got == (None if switch else "Centrifugal Pump")


def test_the_engineer_to_confirm_note_reaches_the_crs(on, monkeypatch):
    """Through the CRS route (`main._crs_content`), not the helper alone."""
    from app import access, submittal_review
    from tests.test_crs_endpoint import _client, _submittal
    from tests.test_crs_endpoint import _run as _review_run

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    submittal_review.ensure_schema()
    doc = _submittal("d1")
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            " document_role) VALUES (?,?,?)",
            (doc, "t", "CONTRACTOR_SUBMITTAL"),
        )
    equipment_title_block.store_to_confirm(
        doc, equipment_title_block.TitleReading(None, "none", [])
    )
    run_id = _review_run(doc)
    try:
        view = _client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview").json()
    finally:
        from app.main import app

        app.dependency_overrides.clear()
    notes = [n["note"] for n in view["review_notes"]]
    assert equipment_title_block.NOTE in notes


def test_no_equipment_in_the_title_block_is_engineer_to_confirm_never_motor(on):
    _doc("d1", _page(["ACME PROJECT", "TECHNICAL DATA", "Doc 1", "Rev 0", "Tag X-1"]))
    row = _run("d1")
    assert row["equipment_type"] is None
    evidence = json.loads(row["equipment_type_evidence"])
    assert evidence["method"] == "engineer_to_confirm" and evidence["reason"] == "none"
    notes = equipment_title_block.for_submittal("d1")
    assert [n["note"] for n in notes] == [equipment_title_block.NOTE]
    assert "names no equipment type" in notes[0]["detail"]


@pytest.mark.parametrize(
    "title",
    [
        ["ACME PROJECT", "PUMP AND MOTOR DATA SHEET", "Doc 1", "Rev 0", "Tag P-1"],
        [
            "CENTRIFUGAL PUMP DATA SHEET",
            "COMPRESSOR DATA SHEET",
            "Doc 1",
            "Rev 0",
            "Tag P-1",
        ],
    ],
)
def test_a_title_block_naming_two_types_is_engineer_to_confirm(on, title):
    _doc("d1", _page(title))
    row = _run("d1")
    assert row["equipment_type"] is None
    evidence = json.loads(row["equipment_type_evidence"])
    assert evidence["reason"] == "ambiguous" and len(evidence["types"]) == 2
    assert "two different" in equipment_title_block.for_submittal("d1")[0]["detail"]


def test_switch_off_a_panel_heading_still_sets_the_type_as_before():
    _doc("d1", _page(["ACME PROJECT", "Doc 1", "Rev 0", "Tag X-1", "Sheet 1"]))
    assert _run("d1")["equipment_type"] == "Motor"
    assert equipment_title_block.for_submittal("d1") == []


def test_no_note_when_the_title_block_named_the_type(on):
    _doc("d1", _page(["CENTRIFUGAL PUMP DATA SHEET", "Doc 1", "Rev 0", "Tag P-1", "x"]))
    _run("d1")
    assert equipment_title_block.for_submittal("d1") == []


def test_an_engineer_confirmed_record_is_not_touched(on):
    _doc(
        "d1",
        _page(["ACME PROJECT", "TECHNICAL DATA", "Doc 1", "Rev 0", "Tag X-1"]),
        confirmed=True,
    )
    assert _run("d1")["equipment_type"] == "Valve"
    assert equipment_title_block.for_submittal("d1") == []


def test_a_title_naming_one_type_by_two_spellings_is_not_ambiguous(on):
    _doc(
        "d1",
        _page(
            ["DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)", "Doc 1", "Rev 0", "x", "y"]
        ),
    )
    assert _run("d1")["equipment_type"] == "Pressure Safety Valve"
