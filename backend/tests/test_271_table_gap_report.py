"""Order 271.4: the table-gap report tells a page with no recorded table from one with a failure."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "table_gap_report.py"
ROWS = [
    ["Material", "Max temp", "Max H2S"],
    ["Carbon steel", "80", "10"],
    ["Duplex", "120", "30"],
    ["Alloy 625", "200", "100"],
    ["Titanium", "150", "50"],
]


@pytest.fixture(scope="module")
def gap():
    spec = importlib.util.spec_from_file_location("table_gap_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page(ruled: bool):
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


def test_probe_separates_a_borderless_table_from_a_ruled_one(gap):
    _doc, borderless = _page(ruled=False)
    _doc2, ruled = _page(ruled=True)
    assert gap.probe_page(borderless) == {"lines": 0, "text": 1}
    assert gap.probe_page(ruled)["lines"] == 1


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE documents (id TEXT, stored_path TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INT, char_count INT, needs_ocr INT,
                            tables_json TEXT);
        CREATE TABLE chunks (document_id TEXT, kind TEXT);
        CREATE TABLE standard_requirements (standard_document_id TEXT, page INT,
                                            requirement_type TEXT);
        """
    )
    return conn


def _tables(rows) -> str:
    return json.dumps(
        {"v": "2", "tables": [{"bbox": [0, 0, 1, 1], "rows": rows, "lines": [0]}]}
    )


def test_pages_with_no_rule_are_split_by_what_the_extractor_recorded(gap):
    conn = _db()
    conn.execute("INSERT INTO documents VALUES ('d', NULL)")
    conn.executemany(
        "INSERT INTO pages VALUES ('d', ?, ?, ?, ?)",
        [
            (1, 500, 0, None),  # text, a rule on it
            (2, 500, 0, _tables(ROWS)),  # text, a recorded table, no rule
            (
                3,
                500,
                0,
                json.dumps({"v": "2", "tables": [], "failed": "table_find_failed"}),
            ),
            (4, 500, 0, None),  # text, nothing recorded, no rule
            (5, 0, 1, None),  # no text: not counted as a page with text
        ],
    )
    conn.execute("INSERT INTO standard_requirements VALUES ('d', 1, 'sentence')")
    conn.execute("INSERT INTO chunks VALUES ('d', 'table')")
    report = gap.report_document(conn, "d")
    assert report["pages"] == 5
    assert report["pages_with_text"] == 4
    assert report["pages_with_text_and_rule"] == 1
    assert report["pages_with_text_no_rule"] == 3
    assert report["no_rule_with_recorded_table"] == 1
    assert report["no_rule_with_recorded_failure"] == 1
    assert report["recorded_failures_by_slug"] == {"table_find_failed": 1}
    assert report["no_rule_with_nothing_recorded"] == 1
    assert report["table_chunks"] == 1
    assert report["pages_read_by_ocr"] == 1


def test_cells_of_recorded_tables_are_counted_as_number_text_or_empty(gap):
    kinds = gap.cell_kinds(
        [
            [
                ["Part", "Material", "Limit"],
                ["Shell", "duplex", "120 C"],
                ["Head", "", "x"],
            ]
        ]
    )
    assert kinds == {"number": 1, "text": 2, "empty": 1}


def test_probe_counts_pages_only_the_text_finder_finds_and_never_prints_text(
    gap, tmp_path, capsys
):
    doc, _page_obj = _page(ruled=False)
    pdf = tmp_path / "borderless.pdf"
    doc.save(str(pdf))
    conn = _db()
    conn.execute("INSERT INTO documents VALUES ('d', ?)", (str(pdf),))
    conn.execute("INSERT INTO pages VALUES ('d', 1, 500, 0, NULL)")
    probe = gap.report_document(conn, "d", probe=True)[
        "probe_of_pages_with_nothing_recorded"
    ]
    assert probe == {
        "probed": 1,
        "pdf_missing": 0,
        "finder_raised": 0,
        "lines_finds": 0,
        "text_only_finds": 1,
    }
    assert "Carbon" not in json.dumps(gap.report_document(conn, "d", probe=True))


def test_a_live_shaped_path_is_refused(gap, tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    with pytest.raises(SystemExit):
        gap.main(["--db", str(live)])
