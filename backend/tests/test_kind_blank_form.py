"""Owner order 1 Nov: a blank form (labels, no values) is kind "unknown", never a
kind guessed from a field label, and never gets an unmarked equipment type.
Invented pages only."""

from __future__ import annotations

import pytest

from app import db, document_kind
from app.blank_form import is_blank_form
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


_LABELS = [
    "SERVICE / P&ID NUMBER",
    "DRAWING NO",
    "SPECIFICATION",
    "PROCEDURE REF",
    "TAG NUMBER",
    "FLUID",
    "OPERATING PRESSURE",
    "DESIGN TEMPERATURE",
    "MANUFACTURER",
    "MODEL",
]


def _blank_rows():
    rows = [f"| {label} | | |" for label in _LABELS]
    rows.append("| REMARKS | By Vendor | TBA |")
    return rows


def _decide(lines):
    pages = [{"page_no": 1, "text": "\n".join(lines)}]
    return document_kind.decide_document_kind(pages)


def test_blank_template_labels_give_unknown_blank_form():
    got = _decide(_blank_rows())
    assert (got.kind, got.method, got.guess) == ("unknown", "blank_form", True)


@pytest.mark.parametrize("label", ["SPECIFICATION", "DRAWING NO", "PROCEDURE REF"])
def test_a_label_row_alone_never_gives_a_kind(label):
    assert _decide([f"| {label} | | |", *_blank_rows()]).kind == "unknown"


def test_label_with_empty_colon_value_counts_as_blank():
    lines = [f"{label}:" for label in _LABELS]
    assert is_blank_form([(1, ln) for ln in lines])
    assert _decide(lines).kind == "unknown"


def test_blank_template_with_its_title_is_a_datasheet():
    got = _decide(["CENTRIFUGAL PUMP DATA SHEET", *_blank_rows()])
    assert got.kind == "datasheet"
    assert got.method == "title_cue"


def test_blank_template_with_its_title_in_a_table_row_is_a_datasheet():
    got = _decide(["| CENTRIFUGAL PUMP DATA SHEET | | |", *_blank_rows()])
    assert got.kind == "datasheet"


def test_filled_datasheet_is_a_datasheet():
    rows = [
        "CENTRIFUGAL PUMP DATA SHEET",
        "| TAG NUMBER | P-101A | |",
        "| FLUID | Seawater | |",
        "| OPERATING PRESSURE | 12.5 bar | |",
        "| DESIGN TEMPERATURE | 80 C | |",
        "| MANUFACTURER | Acme Pumps | |",
        "| MODEL | CP-200 | |",
        "| SERVICE / P&ID NUMBER | | |",
    ]
    assert not is_blank_form([(1, ln) for ln in rows])
    assert _decide(rows).kind == "datasheet"


def test_real_pid_title_block_is_a_drawing():
    rows = [
        "PIPING AND INSTRUMENTATION DIAGRAM",
        "Unit 100 cooling water",
        "Sheet 1 of 2",
        "Rev B 12-03-2026",
    ]
    assert _decide(rows).kind == "drawing"


def test_blank_form_never_gets_equipment_guess_from_labels():
    rows = ["| CENTRIFUGAL PUMP SERVICE | | |", *_blank_rows()]
    got = _decide(rows)
    assert got.kind == "unknown"
    pages = [{"page_no": 1, "text": "\n".join(rows)}]
    assert not document_kind.body_equipment_allowed(pages, "doc_none", None)


def test_unmarked_equipment_title_guess_stays_a_marked_guess():
    got = _decide(["CENTRIFUGAL PUMP", "Notes"])
    assert got.guess is True
