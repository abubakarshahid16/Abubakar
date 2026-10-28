"""Order 271.4: a table with no ruling is kept when it reads like a grid, and only when the switch is on."""

from __future__ import annotations

import json

import pymupdf
import pytest

from app import db, extract, tables
from app.config import settings

ROWS = [
    ["Material", "Max temp", "Max H2S"],
    ["Carbon steel", "80", "10"],
    ["Duplex", "120", "30"],
    ["Alloy 625", "200", "100"],
    ["Titanium", "150", "50"],
]


def _page(ruled: bool = False):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, row in enumerate(ROWS):
        for j, cell in enumerate(row):
            page.insert_text((60 + j * 150, 100 + i * 22), cell, fontsize=11)
    if ruled:
        for i in range(len(ROWS) + 1):
            page.draw_line((50, 86 + i * 22), (500, 86 + i * 22))
        for j in range(4):
            page.draw_line((50 + j * 150, 86), (50 + j * 150, 86 + len(ROWS) * 22))
    return doc, page


def _tables(page):
    return extract.page_tables_checked(page, page.get_text("text") or "")


def test_a_borderless_table_is_kept_only_when_the_switch_is_on(monkeypatch):
    _doc, page = _page()
    monkeypatch.setattr(settings, "aligned_text_tables_enabled", False)
    assert _tables(page) == ([], None)
    monkeypatch.setattr(settings, "aligned_text_tables_enabled", True)
    found, failed = _tables(page)
    assert failed is None and len(found) == 1
    assert found[0]["aligned"] is True
    assert ["Carbon steel", "80", "10"] in found[0]["rows"]


def test_a_ruled_table_is_still_read_by_the_ruled_finder(monkeypatch):
    _doc, page = _page(ruled=True)
    monkeypatch.setattr(settings, "aligned_text_tables_enabled", True)
    found, _failed = _tables(page)
    assert found and "aligned" not in found[0]


GRID = [["Class", "Limit"], ["150", "1.5"], ["300", "1.5"], ["600", "1.5"]]
GOOD = {"column_consistency": 1.0, "split_rate": 0.0}


def test_the_grid_gate_keeps_a_regular_grid():
    assert extract.aligned_grid_ok(GRID, GOOD)


@pytest.mark.parametrize(
    ("texts", "score"),
    [
        (GRID[:2], GOOD),  # too few rows
        (GRID, {**GOOD, "column_consistency": 0.5}),  # rows that do not repeat one shape
        (GRID, {**GOOD, "split_rate": 0.1}),  # words cut across two cells
        ([["x" * 90, "y" * 90]] * 4, GOOD),  # prose cut into long cells
        ([], GOOD),
    ],
)
def test_the_grid_gate_refuses_what_does_not_read_like_a_grid(texts, score):
    assert not extract.aligned_grid_ok(texts, score)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield tmp_path
    db.reset_connection()


def _stored(storage, tables_json):
    doc = pymupdf.open()
    doc.new_page()  # a page the PDF-side parser finds no table on
    pdf = storage / "std.pdf"
    doc.save(str(pdf))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES ('d','d.pdf','sha',1,?,'ready',1,'2026-10-28T00:00:00Z')",
            (str(pdf),),
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,batch_no,tables_json)"
            " VALUES ('d',1,'t',1,0,?)",
            (tables_json,),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,kind,text,"
            "token_count,content_hash,retrievable) VALUES ('c1','d','d.pdf',0,1,1,'table','t',1,'h',1)"
        )


def test_the_standards_parser_reads_the_stored_rows_of_an_aligned_table(storage):
    stored = {"v": "2", "tables": [{"bbox": [0, 0, 1, 1], "rows": ROWS, "lines": [0], "aligned": True}]}
    _stored(storage, json.dumps(stored))
    parses = tables.parse_document_tables("d", allowed_document_ids=frozenset({"d"}))
    assert [p.parsed for p in parses] == [True]
    assert ["Carbon steel", "80", "10"] in parses[0].rows


def test_a_stored_table_that_is_not_aligned_stays_unparsed_when_the_ruled_parser_finds_none(storage):
    stored = {"v": "2", "tables": [{"bbox": [0, 0, 1, 1], "rows": ROWS, "lines": [0]}]}
    _stored(storage, json.dumps(stored))
    parses = tables.parse_document_tables("d", allowed_document_ids=frozenset({"d"}))
    assert [p.parsed for p in parses] == [False]
