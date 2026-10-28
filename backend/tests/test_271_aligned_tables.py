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
        (
            GRID,
            {**GOOD, "column_consistency": 0.5},
        ),  # rows that do not repeat one shape
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
    stored = {
        "v": "2",
        "tables": [{"bbox": [0, 0, 1, 1], "rows": ROWS, "lines": [0], "aligned": True}],
    }
    _stored(storage, json.dumps(stored))
    parses = tables.parse_document_tables("d", allowed_document_ids=frozenset({"d"}))
    assert [p.parsed for p in parses] == [True]
    assert ["Carbon steel", "80", "10"] in parses[0].rows


def test_a_stored_table_that_is_not_aligned_stays_unparsed_when_the_ruled_parser_finds_none(
    storage,
):
    stored = {"v": "2", "tables": [{"bbox": [0, 0, 1, 1], "rows": ROWS, "lines": [0]}]}
    _stored(storage, json.dumps(stored))
    parses = tables.parse_document_tables("d", allowed_document_ids=frozenset({"d"}))
    assert [p.parsed for p in parses] == [False]


def _captioned_page(note: bool = True):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(
        (60, 60), "Table 2 Limits for materials in sour service", fontsize=12
    )
    for i, row in enumerate(ROWS):
        for j, cell in enumerate(row):
            page.insert_text((60 + j * 130, 110 + i * 22), cell, fontsize=10)
    if note:
        page.insert_text(
            (60, 110 + len(ROWS) * 22 + 10),
            "NOTE 1 Values are for annealed material.",
            fontsize=9,
        )
    return doc, page


@pytest.mark.parametrize("note", [False, True])
def test_a_table_with_a_caption_above_and_a_note_below_is_kept_without_them(
    monkeypatch, note
):
    _doc, page = _captioned_page(note)
    monkeypatch.setattr(settings, "aligned_text_tables_enabled", True)
    found, failed = _tables(page)
    assert failed is None and len(found) == 1
    table = found[0]
    text = " ".join(c for row in table["rows"] for c in row)
    assert (
        "Table 2" not in text
        and "NOTE" not in text
        and "Carbon" in text
        and "Titanium" in text
    )
    lines = page.get_text("text").split("\n")
    kept = {lines[i] for i in table["lines"]}
    assert not any(
        line.startswith(("Table 2", "NOTE 1")) for line in kept
    )  # they stay in the prose
    assert "Carbon steel" in kept


def test_the_grid_span_leaves_out_rows_that_fill_fewer_cells_than_the_grid():
    rows = [
        ["Table 2 Limits", "for materials", "", ""],
        ["A", "B", "C", "D"],
        ["1", "2", "3", "4"],
        ["5", "6", "7", "8"],
        ["NOTE 1", "", "", ""],
    ]
    assert extract._grid_span(rows) == (1, 3)
    assert extract._grid_span([["A", "B"], ["1", "2"]]) == (0, 1)
    assert extract._grid_span([["", ""], ["", ""]]) is None
    assert (
        extract._grid_span([["A", ""], ["B", ""]]) is None
    )  # one filled column is a list, not a grid


def _sentence_grid(n: int = 10) -> list[list[str]]:
    # a page of one-template requirement sentences cut into one-word cells (s3's probe on #1413)
    words = "The inlet piping shall be sized so that line {} holds.".split()
    return [[w.format(i) for w in words] for i in range(1, n + 1)]


def test_a_page_of_one_template_sentences_is_prose_not_a_table():
    assert extract.aligned_grid_ok(_sentence_grid(), GOOD) is False
    # the same shape without a modal or a full stop and under eight words is a table
    assert extract.aligned_grid_ok([r[:5] for r in _sentence_grid()], GOOD) is True
    # a full stop alone makes a long row a sentence; a modal alone does too
    no_modal = [[w.replace("shall", "is") for w in r] for r in _sentence_grid()]
    assert extract.aligned_grid_ok(no_modal, GOOD) is False
    no_stop = [[w.replace("holds.", "holds") for w in r] for r in _sentence_grid()]
    assert extract.aligned_grid_ok(no_stop, GOOD) is False


def test_a_modal_phrase_in_one_column_of_a_real_table_is_still_a_table():
    rows = [["Item", "Part", "Duty", "Qty"]] + [
        [str(i), "Pump", "shall be tested", str(i)] for i in range(1, 7)
    ]
    assert extract.aligned_grid_ok(rows, GOOD) is True


def test_one_long_sentence_row_among_table_rows_does_not_sink_the_table():
    rows = [
        ["Material", "Max temp", "Remarks"],
        [
            "Carbon steel",
            "80",
            "Annealed material shall be used above this limit unless the owner agrees.",
        ],
        ["Duplex", "120", "None"],
        ["Alloy 625", "200", "None"],
        ["Titanium", "150", "None"],
    ]
    assert extract.aligned_grid_ok(rows, GOOD) is True


def test_a_failure_of_the_aligned_finder_is_named_not_silent(monkeypatch):
    _doc, page = _page()
    monkeypatch.setattr(settings, "aligned_text_tables_enabled", True)

    def boom(*_a, **_k):
        raise RuntimeError("geometry the finder cannot read")

    monkeypatch.setattr(pymupdf.Page, "find_tables", boom)
    assert _tables(page) == ([], "aligned_table_find_failed")
