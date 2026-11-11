"""#918 (PF3), the rest: a reader that FAILED on a page says so, with a named
reason, and the run's reading is incomplete. Before, each of these returned
"nothing" and nothing said it had failed.

Invented data only; no model, no socket.
"""
from __future__ import annotations

import json

import pytest

from app import chunker as ch
from app import datasheets, db, extract, page_ledger
from app.config import settings

NOW = "2026-10-14T00:00:00Z"
PROSE = ("Marking shall be applied to every component before it leaves the shop. "
         "Marks shall be legible and durable after heat treatment. ") * 3


class _Page:
    def __init__(self, drawings=None, find=None):
        self._d, self._f = drawings, find
        self.rotation = 0

    def get_drawings(self):
        if isinstance(self._d, Exception):
            raise self._d
        return self._d or []

    def find_tables(self, strategy=None):
        raise self._f


def test_a_table_reader_that_raises_names_why_instead_of_returning_nothing():
    tables, why = extract.page_tables_checked(_Page(drawings=RuntimeError("boom")), "x")
    assert tables == [] and why == "table_get_drawings_failed"
    many = [object()] * (extract.MIN_TABLE_PATHS + 1)
    tables, why = extract.page_tables_checked(_Page(drawings=many, find=RuntimeError("boom")), "x")
    assert tables == [] and why == "table_find_failed"
    assert extract.page_tables(_Page(drawings=RuntimeError("boom")), "x") == []     # old callers unchanged


def test_a_page_with_no_ruling_is_not_a_failure():
    assert extract.page_tables_checked(_Page(drawings=[]), "x") == ([], None)


def test_the_failure_is_stored_with_the_page_and_the_chunker_records_it(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    try:
        stored = extract._tables_json(_Page(drawings=RuntimeError("boom")), "x", "x")
        assert json.loads(stored)["failed"] == "table_get_drawings_failed"
        assert ch._table_failures({1: stored, 2: None, 3: "{not json"}) == {1: "table_get_drawings_failed"}
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                "page_count,uploaded_at) VALUES ('d918c','std.pdf','sha-918c',1,'/tmp/std','chunking',1,?)", (NOW,))
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no,tables_json)"
                " VALUES ('d918c',1,?,?,0,0,?)", (PROSE, len(PROSE), stored))
        ch.chunk_document("d918c")
        rows = db.connect().execute(
            "SELECT rule, scope, page_start FROM exclusions WHERE document_id='d918c'").fetchall()
        assert [(r["rule"], r["scope"], r["page_start"]) for r in rows] == [
            ("table_get_drawings_failed", "chunk", 1)]
    finally:
        db.reset_connection()


def test_a_code_reader_that_fails_on_a_page_is_recorded_for_the_run():
    token = datasheets._PAGE_FAILURES.set({})
    try:
        assert datasheets._grid_facts_from_pdf_page("D:/no/such/file.pdf", 2) == []
        failures = datasheets._PAGE_FAILURES.get()
    finally:
        datasheets._PAGE_FAILURES.reset(token)
    assert failures == {2: {"grid"}}


def test_the_reader_summary_keeps_the_failures_and_the_notes_with_or_without_an_ai_reader():
    summary = datasheets.reader_summary(None, {}, pages=[1, 2], page_failures={2: {"geometry", "grid"}},
                                        reading_notes=["hidden sheet 2 skipped"])
    assert summary["page_failures"] == {"2": ["geometry", "grid"]}
    assert summary["reading_notes"] == ["hidden sheet 2 skipped"]
    assert "page_failures" not in datasheets.reader_summary(None, {}, pages=[1])


PAGES = {"pages_total": 3, "pages_not_read_into_fields": []}


def test_a_failed_code_reader_makes_the_reading_incomplete():
    clean = page_ledger.reading_gaps({"engine": "off", "pages": 3}, PAGES)
    assert clean["reading"]["status"] == page_ledger.READING_COMPLETE
    failed = page_ledger.reading_gaps({"engine": "off", "pages": 3, "page_failures": {"2": ["geometry"]}}, PAGES)
    assert failed["reading"]["status"] == page_ledger.READING_INCOMPLETE
    assert failed["reading"]["incomplete_pages"] == [2]
    assert "geometry" in failed["reading"]["failed_pages"]["2"]


def test_something_the_office_reader_left_out_makes_the_reading_incomplete():
    noted = page_ledger.reading_gaps({"engine": "off", "pages": 3, "reading_notes": ["sheet 1 cut at 5000 rows"]}, PAGES)
    assert noted["reading"]["status"] == page_ledger.READING_INCOMPLETE
    assert noted["reading"]["notes"] == ["sheet 1 cut at 5000 rows"]
