"""A FILLED sheet whose text prints labels and values on separate lines (a labels
block then a values block, or label/value lines interleaved) is not a blank
form, and keeps its equipment type. Invented pages only."""

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


_VALUES = ["P-101A", "Seawater", "12.5 bar", "80 C", "Acme Pumps", "CP-200"]
_LABELS = [
    "TAG NUMBER:",
    "FLUID:",
    "OPERATING PRESSURE:",
    "DESIGN TEMPERATURE:",
    "MANUFACTURER:",
    "MODEL:",
]


def _pages(lines):
    return [{"page_no": 1, "text": "\n".join(lines)}]


@pytest.mark.parametrize("layout", ["blocks", "interleaved"])
def test_filled_sheet_with_values_on_separate_lines_is_not_blank(layout):
    if layout == "blocks":
        body = _LABELS + _VALUES
    else:
        body = [x for pair in zip(_LABELS, _VALUES, strict=True) for x in pair]
    rows = ["CENTRIFUGAL PUMP DATA SHEET", *body]
    assert not is_blank_form([(1, ln) for ln in rows])
    got = document_kind.decide_document_kind(_pages(rows))
    assert got.kind == "datasheet"
    assert got.method == "title_cue"
    assert document_kind.body_equipment_allowed(_pages(rows), "doc_x", None)


def test_filled_sheet_without_a_data_sheet_title_keeps_equipment_allowed():
    rows = ["CENTRIFUGAL PUMP", *_LABELS, *_VALUES]
    got = document_kind.decide_document_kind(_pages(rows))
    assert got.method != "blank_form"
    assert document_kind.body_equipment_allowed(_pages(rows), "doc_x", None)


def test_labels_alone_on_separate_lines_are_still_blank():
    assert is_blank_form([(1, ln) for ln in _LABELS])


def test_transmittal_cover_is_not_misread_as_blank_form():
    rows = [
        "To:",
        "From:",
        "Date:",
        "Subject:",
        "Ref:",
        "Acme Projects Ltd",
        "Site Office",
        "12 March 2026",
        "Pump submittal",
        "Please find enclosed",
    ]
    got = document_kind.decide_document_kind(_pages(rows))
    assert got.method != "blank_form"
    assert got.kind == "unknown" or got.guess is False
