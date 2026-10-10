"""Planner 2026-10-10 (F-b, roadmap R5): a review re-reads a datasheet whose
stored facts were read by an older reader version.

A fix to the reader (#725 F3: "340 psig (By Contractor)" is a value, not a
blank) reached no live review, because a review reuses stored facts forever:
the live PSV still had 24 blank fields where a re-read gives 6. Now the one
guard (`submittal_review.ensure_facts_extracted`) also re-reads, with
replace=True (supersede, never delete; an engineer-confirmed fact survives),
when the current rule-read facts carry another reader version. Invented data.
"""
from __future__ import annotations

import pytest

from app import datasheets, db, submittal_review
from app.config import settings

NOW = "2026-10-10T00:00:00Z"


@pytest.fixture
def sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "fb.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                     "uploaded_at) VALUES ('sub','s.pdf','x',1,'s.pdf','ready',1,?)", (NOW,))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
                     "text,token_count,content_hash,retrievable) VALUES ('c','sub','s.pdf',0,1,1,NULL,'prose',"
                     "'Set pressure 340 psig',4,'h',1)")
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES ('run','sub','pending',?,?)", (NOW, NOW))
    yield "sub"
    db.reset_connection()


def _fact(version, method="extracted", label="Set pressure"):
    return datasheets.create_fact(submittal_document_id="sub", chunk_id="c", review_run_id="run",
                                  field_label=label, raw_value="340 psig", page=1,
                                  extraction_method=method, extractor_version=version)


def test_facts_from_another_reader_version_are_stale(sheet):
    assert datasheets.facts_reader_stale(sheet) is False                # no facts: nothing to re-read
    _fact(datasheets.rule_reader_version())
    assert datasheets.facts_reader_stale(sheet) is False                # current reader
    _fact("datasheets+tables+blank_markers@000000000000", label="Design pressure")
    assert datasheets.facts_reader_stale(sheet) is True                 # an older reader


def test_a_fact_with_no_version_is_stale_but_geometry_and_confirmed_facts_are_not_judged(sheet):
    f = _fact(None)
    assert datasheets.facts_reader_stale(sheet) is True
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET confirmed_by = NULL, superseded_at = ? WHERE id = ?", (NOW, f["id"]))
    _fact("geometry_reader@abc", method="geometry", label="Orifice")     # its own reader, its own version
    assert datasheets.facts_reader_stale(sheet) is False


def test_the_guard_re_reads_a_stale_sheet_with_replace(sheet, monkeypatch):
    calls = []
    monkeypatch.setattr(datasheets, "extract_facts", lambda doc, **kw: calls.append(kw.get("replace")) or {})
    submittal_review.ensure_facts_extracted(sheet, frozenset({sheet}))
    assert calls == [False]                                             # no facts: first read
    _fact(datasheets.rule_reader_version())
    calls.clear()
    submittal_review.ensure_facts_extracted(sheet, frozenset({sheet}))
    assert calls == []                                                  # current facts: reused
    _fact("datasheets+tables+blank_markers@000000000000", label="Design pressure")
    submittal_review.ensure_facts_extracted(sheet, frozenset({sheet}))
    assert calls == [True]                                              # older reader: read again
