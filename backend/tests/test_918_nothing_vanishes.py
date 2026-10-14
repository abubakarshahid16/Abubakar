"""#918 (PF3), the chunker's two places: a fragment the runt pass drops leaves an
`exclusions` row, and the token-ceiling guard is a raise, not an `assert`
(`python -O` removes asserts).

Invented text only.
"""
from __future__ import annotations

import pytest

from app import chunker as ch
from app import db
from app.config import settings

NOW = "2026-10-13T00:00:00Z"
PROSE = ("Marking shall be applied to every component before it leaves the shop. "
         "Marks shall be legible and durable after heat treatment. ") * 3


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _blocks():
    return [ch.Block("prose", PROSE, 1, 1, "1 Marking", ch.count_tokens(PROSE)),
            ch.Block("prose", "12.", 1, 1, "2 Other", 2)]


def test_a_dropped_fragment_is_handed_back_to_be_recorded():
    dropped: list = []
    chunks = ch.build_chunks(_blocks(), None, dropped)
    assert [c.text for c in dropped] == ["12."]
    assert all("12." != c.text for c in chunks)


def _add_document(doc="d918"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'chunking',1,?)",
            (doc, "std.pdf", "sha-918", "/tmp/std", NOW))
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,?,?,?,0,0)", (doc, 1, PROSE, len(PROSE)))
    return doc


def test_a_stray_fragment_leaves_an_exclusion_row(temp_db, monkeypatch):
    doc = _add_document()
    real = ch.build_chunks

    def with_a_stray(blocks, vocab=None, dropped=None):
        out = real(blocks + [ch.Block("prose", "12.", 1, 1, "2 Other", 2)], vocab, dropped)
        return out
    monkeypatch.setattr(ch, "build_chunks", with_a_stray)
    ch.chunk_document(doc)
    rows = db.connect().execute("SELECT rule, scope, text_sample FROM exclusions WHERE document_id=?", (doc,)).fetchall()
    assert [(r["rule"], r["scope"], r["text_sample"]) for r in rows if r["rule"] == "stray_fragment"] == [
        ("stray_fragment", "chunk", "12.")]


def test_the_ceiling_guard_raises_and_is_not_an_assert(temp_db, monkeypatch):
    doc = _add_document("d918b")
    big = ch.Block("prose", PROSE, 1, 1, "1 Marking", settings.chunk_max_tokens + 50)
    monkeypatch.setattr(ch, "build_chunks", lambda blocks, vocab=None, dropped=None: [big])
    with pytest.raises(RuntimeError, match="token ceiling"):
        ch.chunk_document(doc)
