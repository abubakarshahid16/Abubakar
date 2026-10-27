"""Order 228.9 (remainder): a ruled, empty value cell beside a label is a blank.

On a datasheet that prints a ruled cell for every answer, a vendor who left a
cell empty used to look like a row the reader missed ("wording appears on page
N: engineer to check"). The geometry now proves it: the cell is a real ruled
cell, the answer column has text elsewhere, and no word, image or drawn shape
lies inside the cell. Invented tables only, drawn with PyMuPDF.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import geometry_blank_cells as gb
from app import geometry_reader as g

XS = [50, 250, 400]
LABELS = [
    ("Rated capacity", "125 m3/h"),
    ("Differential head", "85 m"),
    ("Design pressure", "10 barg"),
    ("Rated relieving capacity", ""),
    ("Orifice designation", ""),
]


def _page(rows=LABELS, *, image_at=None, shape_at=None, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    ys = [60 + 24 * i for i in range(len(rows) + 1)]
    for y in ys:
        page.draw_line((XS[0], y), (XS[-1], y), width=0.6)
    for x in XS:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.6)
    for i, (label, value) in enumerate(rows):
        page.insert_text((XS[0] + 4, ys[i] + 15), label, fontsize=9)
        if value:
            page.insert_text((XS[1] + 4, ys[i] + 15), value, fontsize=9)
    if image_at is not None:
        cell = pymupdf.Rect(XS[1] + 6, ys[image_at] + 6, XS[1] + 40, ys[image_at] + 18)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        pix.clear_with(120)
        page.insert_image(cell, pixmap=pix)
    if shape_at is not None:
        page.draw_rect(
            pymupdf.Rect(XS[1] + 8, ys[shape_at] + 8, XS[1] + 60, ys[shape_at] + 16),
            fill=(0, 0, 0),
        )
    if rotation:
        page.set_rotation(rotation)
    return doc, page


def _rows(page):
    return {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}


def test_an_empty_ruled_cell_beside_a_label_is_a_blank_with_its_box():
    doc, page = _page()
    try:
        rows = _rows(page)
    finally:
        doc.close()
    for label in ("Rated relieving capacity", "Orifice designation"):
        row = rows[label]
        assert row["is_blank"] is True and row["blank_marker"] == gb.MARKER
        assert row["value"] is None and row["value_text"] == ""
        assert row["bbox"][0] >= XS[1] - 1 and row["label_bbox"] is not None
    assert gb.MARKER == "empty cell" and gb.MARKER != "______"


def test_filled_rows_are_unchanged():
    doc, page = _page()
    try:
        rows = _rows(page)
    finally:
        doc.close()
    assert (
        rows["Rated capacity"]["value_text"],
        rows["Rated capacity"]["is_blank"],
    ) == (
        "125 m3/h",
        False,
    )
    assert rows["Design pressure"]["value"] == "10"


@pytest.mark.parametrize("kind", ["image_at", "shape_at"])
def test_a_cell_with_an_image_or_a_drawn_shape_in_it_is_not_a_blank(kind):
    doc, page = _page(**{kind: 3})
    try:
        rows = _rows(page)
    finally:
        doc.close()
    assert "Rated relieving capacity" not in rows, "something is drawn in the cell"
    assert rows["Orifice designation"]["is_blank"] is True, (
        "the other empty cell still is"
    )


def test_a_word_inside_the_cell_means_it_is_not_bare():
    doc, page = _page()
    try:
        cell = [XS[1], 60 + 24 * 3, XS[2], 60 + 24 * 4]
        assert gb.cell_is_bare(page, cell) is True
        page.insert_text((XS[1] + 6, 60 + 24 * 3 + 14), "see note", fontsize=8)
        assert gb.cell_is_bare(page, cell) is False
    finally:
        doc.close()


def test_a_rotated_page_proves_nothing():
    doc, page = _page(rotation=90)
    try:
        assert gb.cell_is_bare(page, [XS[1], 132, XS[2], 156]) is False
        candidate = {"empty_cell": True, "bbox": [XS[1], 132, XS[2], 156]}
        assert gb.keep_bare(page, [candidate]) == []
    finally:
        doc.close()


def test_an_answer_column_with_too_few_answers_is_not_proof():
    rows = [
        ("Rated capacity", "125 m3/h"),
        ("Orifice designation", ""),
        ("Fluid phase", ""),
    ]
    doc, page = _page(rows)
    try:
        table_rows = _rows(page)
    finally:
        doc.close()
    assert "Orifice designation" not in table_rows and "Fluid phase" not in table_rows


def test_no_candidate_without_a_ruled_cell_to_its_right():
    table = {
        "rows": [{"cells": [{"column": 0, "text": "Label", "bbox": [0, 0, 1, 1]}]}]
    }
    cells = table["rows"][0]["cells"]
    assert gb.rows(table, 0, cells, [0]) == []


def test_end_to_end_the_blank_is_a_stored_fact_with_its_marker(tmp_path, monkeypatch):
    from app import datasheets, db
    from app.config import settings
    from tests.test_datasheet_ai import _ingest

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "blank.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    db.reset_connection()
    db.init_db()
    try:
        rows = [
            ("Design pressure", "10 barg"),
            ("Design temperature", "50 C"),
            ("Operating pressure", "8 barg"),
            ("Rated relieving capacity", ""),
            ("Orifice designation", ""),
        ]
        drawn, _ = _page(rows)
        drawn.save(str(tmp_path / "d.pdf"))
        drawn.close()
        doc = _ingest(str(tmp_path / "d.pdf"))
        datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
        facts = datasheets.list_facts(doc, allowed_document_ids=frozenset({doc}))
    finally:
        db.reset_connection()
    blanks = {f["field_name"]: f for f in facts if f["is_blank"]}
    assert any("rated relieving capacity" in name for name in blanks), sorted(blanks)
    assert all(f["blank_marker"] == gb.MARKER for f in blanks.values()), blanks


def _grid(rows, xs):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    ys = [60 + 24 * i for i in range(len(rows) + 1)]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.6)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.6)
    for i, cells in enumerate(rows):
        for j, text in enumerate(cells):
            if text:
                page.insert_text((xs[j] + 4, ys[i] + 15), text, fontsize=9)
    return doc, page


def _grid_rows(rows, xs):
    doc, page = _grid(rows, xs)
    try:
        return {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}
    finally:
        doc.close()


def test_a_value_line_under_an_empty_label_cell_is_not_a_blank():
    got = _grid_rows(
        [
            ("Rated capacity", "125", "m3/h"),
            ("Differential head", "85", "m"),
            ("Design pressure", "10", "barg"),
            ("Material", "Carbon steel", ""),
            ("", "Class 300", ""),
            ("", "Forged", ""),
        ],
        [50, 200, 330, 450],
    )
    assert "Class 300" not in got and "Forged" not in got, sorted(got)


def test_a_note_in_the_value_column_with_no_label_is_not_a_blank():
    got = _grid_rows(
        [
            ("Rated capacity", "125 m3/h", "per API 520"),
            ("Differential head", "85 m", "at rated flow"),
            ("Design pressure", "10 barg", "gauge"),
            ("", "or equivalent", ""),
            ("Orifice designation", "", ""),
        ],
        [50, 200, 330, 450],
    )
    assert "or equivalent" not in got, sorted(got)
    assert got["Orifice designation"]["is_blank"] is True, "a real label still is"


def _one_path_grid(rows, xs, *, background=False):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    ys = [60 + 24 * i for i in range(len(rows) + 1)]
    if background:
        page.draw_rect(pymupdf.Rect(xs[0], ys[0], xs[-1], ys[-1]), fill=(1, 1, 1), color=None)
    shape = page.new_shape()
    for y in ys:
        shape.draw_line((xs[0], y), (xs[-1], y))
    for x in xs:
        shape.draw_line((x, ys[0]), (x, ys[-1]))
    shape.finish(width=0.6)
    shape.commit()
    for i, cells in enumerate(rows):
        for j, text in enumerate(cells):
            if text:
                page.insert_text((xs[j] + 4, ys[i] + 15), text, fontsize=9)
    return doc, page


@pytest.mark.parametrize("background", [False, True])
def test_a_grid_drawn_as_one_path_or_on_a_fill_still_gives_blanks(background):
    doc, page = _one_path_grid(
        [
            ("Rated capacity", "125 m3/h"),
            ("Differential head", "85 m"),
            ("Design pressure", "10 barg"),
            ("Orifice designation", ""),
        ],
        [50, 250, 400],
        background=background,
    )
    try:
        got = {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}
    finally:
        doc.close()
    assert got["Orifice designation"]["is_blank"] is True


def test_a_mark_drawn_inside_the_cell_of_a_one_path_grid_still_blocks_the_blank():
    doc, page = _one_path_grid(
        [
            ("Rated capacity", "125 m3/h"),
            ("Differential head", "85 m"),
            ("Design pressure", "10 barg"),
            ("Orifice designation", ""),
        ],
        [50, 250, 400],
    )
    page.draw_rect(pymupdf.Rect(260, 60 + 24 * 3 + 8, 310, 60 + 24 * 3 + 16), fill=(0, 0, 0))
    try:
        got = {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}
    finally:
        doc.close()
    assert "Orifice designation" not in got


def test_a_value_pushed_into_the_label_cell_is_not_a_label_with_an_empty_answer():
    got = _grid_rows(
        [
            ("Rated capacity", "125", "m3/h"),
            ("Differential head", "85", "m"),
            ("Design pressure", "10", "barg"),
            ("Design temperature 120 degC", "", ""),
        ],
        [50, 200, 330, 450],
    )
    assert "Design temperature 120 degC" not in got, sorted(got)
