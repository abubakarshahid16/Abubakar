"""Issue #168, criterion 2: "incremental index updates supported."

THE CLAIM. Re-ingesting one document only re-indexes that document, not the
whole corpus, and re-chunking a document whose content has not changed is a
genuine no-op rather than a full rebuild.

`chunker.chunk_document`'s docstring already asserts this ("Idempotent -
re-running replaces rows") and the mechanism is `documents.chunk_signature`
(see backend/app/db.py and chunker.py `_chunk_signature`): a hash of the
document's sha256 plus its extracted page text. `chunk_document` skips the
rebuild entirely when the stored signature still matches, unless `force=True`.

Nothing in this codebase exercised that skip path directly before this test -
grepping the suite for `chunk_signature` before this test was added found zero
hits. This proves two things the issue's criterion needs, on a REAL document
ingested and chunked the ordinary way:

  1. Re-chunking with unchanged content does not touch this document's chunk
     rows at all (same chunk ids, same content hashes - not just "the same
     count").
  2. A second, unrelated document's chunks are never touched by re-chunking
     the first - "incremental" means single-document scope, not merely
     "sometimes skips work."

Mutation: deleting the `if not force and existing and doc["chunk_signature"]
== signature:` early-return in chunker.py (or its `force` check) would make
this test fail, since re-chunking would then always rewrite the chunk rows
with fresh ids/timestamps.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, submittal_review
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.main import app

NOW = "2026-09-24T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "incr.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _ingest(name: str, lines: list[str]) -> str:
    path = settings.data_dir / name
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 16), line)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    extract_document(doc_id)
    chunk_document(doc_id)
    return doc_id


def _chunk_rows(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT id, content_hash, ordinal FROM chunks WHERE document_id = ?"
        " ORDER BY ordinal", (doc_id,)).fetchall()]


def test_rechunking_unchanged_content_leaves_chunk_rows_untouched():
    doc_id = _ingest("std-a.pdf", [
        "5.3.3 Noise",
        "The noise level of rotating equipment shall not exceed 90 dB(A) at",
        "one metre from the equipment surface under rated operating conditions.",
    ])
    before = _chunk_rows(doc_id)
    assert before, "precondition: the document actually produced chunks"

    # Re-chunk with no change to the underlying pages/sha256 - this is what
    # a re-ingestion of the same unmodified document does.
    result = chunk_document(doc_id)

    after = _chunk_rows(doc_id)
    assert after == before, (
        "re-chunking unchanged content rewrote the chunk rows - incremental "
        "indexing (skip-if-unchanged via documents.chunk_signature) is not "
        "actually happening"
    )
    # The count-equality check above is not enough by itself: a full rebuild
    # from deterministic input can legitimately reproduce byte-identical rows
    # (chunk ids/content hashes are derived from content, not randomness), so
    # "before == after" alone would still pass even if the skip path were
    # deleted and every re-chunk did a real DELETE+INSERT. The explicit
    # `skipped` flag is what actually distinguishes "skipped the rebuild"
    # from "rebuilt and happened to match" - assert it directly.
    assert result.get("skipped") is True and result.get("chunks_this_run") == 0, (
        f"chunk_document did not report skipping the rebuild: {result}"
    )


def test_rechunking_one_document_never_touches_another_documents_chunks():
    doc_a = _ingest("std-a2.pdf", [
        "5.3.3 Noise",
        "The noise level of rotating equipment shall not exceed 90 dB(A).",
    ])
    doc_b = _ingest("std-b2.pdf", [
        "6.1.1 Vibration",
        "The vibration velocity shall not exceed 4.5 mm/s RMS on the casing.",
    ])
    before_b = _chunk_rows(doc_b)
    assert before_b, "precondition: doc_b has chunks of its own"

    # Force a real re-chunk of doc_a only - the scenario a single re-ingested
    # document triggers.
    chunk_document(doc_a, force=True)

    after_b = _chunk_rows(doc_b)
    assert after_b == before_b, (
        "re-chunking one document changed another document's chunk rows - "
        "this is corpus-wide reindexing, not incremental per-document "
        "indexing"
    )
