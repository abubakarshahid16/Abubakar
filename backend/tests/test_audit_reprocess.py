"""Ingestion defects that had to be fixed BEFORE the live corpus is re-processed
(audit 2026-09-30). Synthetic PDFs and rows only; no real recognition runs, and
the embedder is faked where the vector values do not matter.

1. A re-chunk deleted EVERY vector of the document (45 -> 0 while 44 of 45
   chunk ids were unchanged): the orphan clean-up ran after the old chunks
   were deleted and before the new ones were inserted. And the embedded count
   must count only vectors of RETRIEVABLE chunks, or a kept vector could stand
   in for a missing one and mark a document READY too early.
2. Legacy (heading-v1) vectors were upgraded only when some chunk had no
   vector at all, while the docstring said "whenever it is processed".
3. An OCR ENGINE failure (missing model, killed worker) failed a readable
   document instead of failing the pages; and search answered from `failed`
   documents.
4. Finishing a document marked EVERY job of it done, not just ingestion.

Mutations M1460-M1469 (scripts/mutations/audit_reprocess.py).
"""
from __future__ import annotations

import concurrent.futures as cf

import numpy as np
import pymupdf
import pytest

from app import db, extract, ingest, keyword, ocr, states, vector_store, vectorcache
from app.chunker import chunk_document
from app.config import settings
from app.db import connect
from app.embedder import EMBEDDING_DIM, LEGACY_PASSAGE_INPUT_VERSIONS, embedding_tag
from app.extract import extract_document
from app.ingest import IngestionWorker

NOW = "2026-09-30T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    vectorcache.invalidate()
    vector_store.reset()
    yield
    db.reset_connection()
    vector_store.reset()


class _Future:
    """A finished future that carries a value OR an exception, as a real
    ProcessPoolExecutor's does - an exception raised in the worker surfaces
    from `result()`, never from `submit()`."""

    def __init__(self, fn, *a, **k):
        self._f = cf.Future()
        try:
            self._f.set_result(fn(*a, **k))
        except BaseException as exc:  # noqa: BLE001 - mirrored, as a pool does
            self._f.set_exception(exc)

    def result(self):
        return self._f.result()


class _InlinePool:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *a, **k):
        return _Future(fn, *a, **k)


class _FakeEmbedder:
    """What `embed_pending` needs, without a model: the vector values do not
    matter to these tests, only which chunks get one and under which tag."""

    class config:
        model_file = "model_qint8_avx512_vnni.onnx"

    def passage_input(self, heading, body):
        return f"{heading}\n{body}" if heading else body

    def embed_passages(self, texts):
        return np.ones((len(texts), EMBEDDING_DIM), dtype="float32")


@pytest.fixture
def fake_embedder(monkeypatch):
    monkeypatch.setattr(ingest.Embedder, "instance", classmethod(lambda cls, cfg=None: _FakeEmbedder()))


def _vector(chunk_id: str, doc_id: str, model: str | None = None) -> tuple:
    return (chunk_id, doc_id, EMBEDDING_DIM,
            np.ones(EMBEDDING_DIM, dtype="float32").tobytes(), model or embedding_tag(), NOW)


def _add_vectors(rows) -> None:
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO chunk_vectors
               (chunk_id, document_id, dim, vector, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""", rows)


# ================================================ 1. a re-chunk keeps vectors

def _four_page_document(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(extract.cf, "ProcessPoolExecutor", _InlinePool)
    pdf = tmp_path / "a.pdf"
    d = pymupdf.open()
    for p in range(4):
        pg = d.new_page()
        y = 72
        pg.insert_text((72, y), f"{p + 1}. SECTION {p + 1} GENERAL", fontsize=11)
        y += 20
        for i in range(12):
            pg.insert_text((72, y), f"{p + 1}.{i + 1} The contractor shall provide pump "
                                    f"casing material item {i} per design basis.", fontsize=9)
            y += 14
    d.save(pdf)
    with connect() as conn:
        conn.execute("""INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                        status, uploaded_at) VALUES ('d1','a.pdf',?,1,?,'extracting',?)""",
                     ("ab" * 32, str(pdf), NOW))
        conn.execute("""INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)
                        VALUES ('j1','d1','extract','running',?,?)""", (NOW, NOW))
    extract_document("d1")
    chunk_document("d1")
    return "d1"


def _chunk_ids(doc_id: str) -> set[str]:
    return {r[0] for r in connect().execute(
        "SELECT id FROM chunks WHERE document_id = ?", (doc_id,))}


def _vector_ids(doc_id: str) -> set[str]:
    return {r[0] for r in connect().execute(
        "SELECT chunk_id FROM chunk_vectors WHERE document_id = ?", (doc_id,))}


def _recognise_extra_text_on_page_4(doc_id: str) -> None:
    conn = connect()
    page4 = conn.execute(
        "SELECT text FROM pages WHERE document_id = ? AND page_no = 4", (doc_id,)).fetchone()[0]
    with conn:
        conn.execute("""INSERT INTO page_ocr (document_id, page_no, text, char_count, engine,
                        model, dpi, box_count, seconds, recognised_at, batch_no)
                        VALUES (?, 4, ?, 10, 'e', 'm', 150, 3, 0.5, ?, 0)""",
                     (doc_id, page4 + "\nAdditional stamped note: approved for construction.", NOW))


def test_a_re_chunk_keeps_the_vectors_of_unchanged_chunks(tmp_path, monkeypatch):
    doc_id = _four_page_document(tmp_path, monkeypatch)
    before = _chunk_ids(doc_id)
    _add_vectors([_vector(c, doc_id) for c in before])

    _recognise_extra_text_on_page_4(doc_id)     # one page's text changes
    chunk_document(doc_id)

    after = _chunk_ids(doc_id)
    kept = before & after
    assert kept and after - before, "precondition: some ids kept, some new"
    # every unchanged chunk keeps its vector; only the orphans go
    assert _vector_ids(doc_id) == kept


def test_a_kept_chunk_whose_heading_changed_loses_its_vector(tmp_path, monkeypatch):
    """The id carries the text's hash, not the heading chain the vector was
    also computed from. A kept id with a different chain is re-embedded."""
    doc_id = _four_page_document(tmp_path, monkeypatch)
    ids = sorted(_chunk_ids(doc_id))
    _add_vectors([_vector(c, doc_id) for c in ids])
    with connect() as conn:     # what an older build said this chunk sat under
        conn.execute("UPDATE chunks SET context = 'Z Some other heading > 9.9' WHERE id = ?",
                     (ids[1],))

    chunk_document(doc_id, force=True)

    assert _chunk_ids(doc_id) == set(ids), "precondition: same ids"
    assert _vector_ids(doc_id) == set(ids) - {ids[1]}


def _partial_document() -> None:
    """Two retrievable chunks (one without a vector) and one excluded chunk
    that still holds a vector from an earlier build."""
    with connect() as conn:
        conn.execute("""INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                        status, chunk_count, chunk_count_total, embedded_count, uploaded_at)
                        VALUES ('p1','p.pdf','sha-p1',1,'/nowhere',?,2,3,0,?)""",
                     (states.PARTIALLY_SEARCHABLE, NOW))
        conn.executemany("""INSERT INTO chunks (id, document_id, filename, ordinal, page_start,
                            page_end, section, kind, text, token_count, content_hash, retrievable)
                            VALUES (?, 'p1', 'p.pdf', ?, 1, 1, '1.1', 'prose', ?, 12, ?, ?)""",
                         [("p1-a", 0, "The pump shall be tested.", "h-a", 1),
                          ("p1-b", 1, "The motor shall be rated.", "h-b", 1),
                          ("p1-x", 2, "The motor shall be rated.", "h-x", 0)])
    _add_vectors([_vector("p1-a", "p1"), _vector("p1-x", "p1")])


def test_a_vector_of_an_excluded_chunk_never_counts_toward_ready():
    """chunk_count is the RETRIEVABLE count; counting a vector of an excluded
    chunk would call this document READY with p1-b unsearchable by meaning."""
    _partial_document()
    IngestionWorker()._finish_if_embedded("p1")
    row = connect().execute(
        "SELECT status, embedded_count FROM documents WHERE id = 'p1'").fetchone()
    assert row["embedded_count"] == 1
    assert row["status"] == states.PARTIALLY_SEARCHABLE


# ============================================ 2. legacy vectors are upgraded

def test_processing_upgrades_legacy_vectors_even_when_every_chunk_has_one(fake_embedder):
    _partial_document()
    legacy = embedding_tag().rsplit("+", 1)[0] + "+" + LEGACY_PASSAGE_INPUT_VERSIONS[0]
    _add_vectors([_vector("p1-a", "p1", legacy), _vector("p1-b", "p1", legacy)])

    result = IngestionWorker().process("p1")

    assert "embed" in result["stages"], result
    models = {r[0]: r[1] for r in connect().execute(
        "SELECT chunk_id, model FROM chunk_vectors WHERE chunk_id IN ('p1-a','p1-b')")}
    assert models == {"p1-a": embedding_tag(), "p1-b": embedding_tag()}
    assert connect().execute(
        "SELECT status FROM documents WHERE id = 'p1'").fetchone()[0] == states.READY


# ================================== 3. an OCR engine failure fails pages only

def _text_page_and_a_scan(tmp_path, monkeypatch) -> str:
    from app import upload

    monkeypatch.setattr(extract.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(settings, "ocr_batch_size", 1)
    monkeypatch.setattr(settings, "ocr_processes", 1)
    d = pymupdf.open()
    pg = d.new_page()
    y = 72
    for i in range(15):
        pg.insert_text((72, y), f"4.{i} The contractor shall provide carbon steel pipe to "
                                f"ASTM A106 grade B item {i}.", fontsize=9)
        y += 14
    d.new_page()          # blank: needs recognition
    d.new_page()          # blank: needs recognition
    path = tmp_path / "spec.pdf"
    d.save(path)
    with open(path, "rb") as fh:
        row, _job, _dup = upload.ingest(fh, "spec.pdf")
    return row["id"]


def _outcome(doc_id: str):
    conn = connect()
    doc = conn.execute("SELECT status, chunk_count, error_message FROM documents WHERE id = ?",
                       (doc_id,)).fetchone()
    pages = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, char_count, error FROM page_ocr WHERE document_id = ?", (doc_id,))}
    rules = {r["page_start"]: (r["rule"], r["reason"]) for r in conn.execute(
        "SELECT page_start, rule, reason FROM exclusions WHERE document_id = ? AND scope='page'",
        (doc_id,))}
    return doc, pages, rules


def test_a_missing_ocr_model_fails_the_pages_not_the_document(tmp_path, monkeypatch, fake_embedder):
    doc_id = _text_page_and_a_scan(tmp_path, monkeypatch)
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)

    def no_model():
        raise FileNotFoundError("det model missing")
    monkeypatch.setattr(ocr, "_build_engine", no_model)

    IngestionWorker().process(doc_id)

    doc, pages, rules = _outcome(doc_id)
    assert doc["status"] == states.READY, doc["error_message"]
    assert doc["chunk_count"] > 0
    assert set(pages) == {2, 3}
    assert all(p["error"].startswith("engine_unavailable: FileNotFoundError") for p in pages.values())
    # the exclusion ledger says recognition FAILED, and why - not "has not run"
    assert rules[2][0] == "ocr_failed" and "det model missing" in rules[2][1]
    assert rules[3][0] == "ocr_failed"
    # and the ingestion job is finished, not failed and retried until poisoned
    assert connect().execute(
        "SELECT state FROM jobs WHERE document_id = ?", (doc_id,)).fetchone()[0] == "done"


def _recognised(stored_path, sha256, page_nos):
    return [(p, "Coating system no. 1 shall achieve a nominal dry film thickness of 80 "
                "micrometres measured in accordance with the referenced standard.",
             0.95, 0.91, 6, 0, 0.8, 0, "", None) for p in page_nos]


class _BreakingPool(_InlinePool):
    """The first RECOGNITION pool's worker dies on its first batch, which
    breaks that pool: later submits to it are refused, as a real
    ProcessPoolExecutor's are. Every later pool works. (`cf` is one module, so
    extraction's pool is this class too - it is left alone.)"""

    broke_once = False

    def __init__(self, *a, **k):
        self._broken = False

    def submit(self, fn, *a, **k):
        if fn is not _recognised:
            return _Future(fn, *a, **k)
        if self._broken:
            raise cf.process.BrokenProcessPool("pool is broken")
        if not type(self).broke_once:
            type(self).broke_once = self._broken = True
            f = cf.Future()
            f.set_exception(cf.process.BrokenProcessPool("a child process terminated abruptly"))
            return f
        return _Future(fn, *a, **k)


def test_a_killed_ocr_worker_fails_its_pages_and_the_rest_are_still_read(
        tmp_path, monkeypatch, fake_embedder):
    import concurrent.futures.process  # noqa: F401 - makes cf.process importable

    doc_id = _text_page_and_a_scan(tmp_path, monkeypatch)
    _BreakingPool.broke_once = False
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _BreakingPool)
    monkeypatch.setattr(ocr, "recognise_batch", _recognised)
    # both scanned pages in ONE round, so both batches meet the same pool
    monkeypatch.setattr(ocr, "round_size", lambda already: 10)

    IngestionWorker().process(doc_id)

    doc, pages, rules = _outcome(doc_id)
    assert doc["status"] == states.READY, doc["error_message"]
    assert pages[2]["error"].startswith("worker_failed: BrokenProcessPool")
    # the dead pool was replaced: the next batch was recognised, not failed
    assert pages[3]["error"] is None and pages[3]["char_count"] > 0


# ============================= 3b. search never answers from a failed document

def _two_documents() -> frozenset[str]:
    with connect() as conn:
        for doc_id, status in (("ok", states.READY), ("bad", states.FAILED)):
            conn.execute("""INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                            status, uploaded_at) VALUES (?, ?, ?, 1, '/nowhere', ?, ?)""",
                         (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", status, NOW))
            conn.execute("""INSERT INTO chunks (id, document_id, filename, ordinal, page_start,
                            page_end, section, kind, text, token_count, content_hash, retrievable)
                            VALUES (?, ?, ?, 0, 1, 1, '4.1', 'prose', ?, 12, ?, 1)""",
                         (f"{doc_id}-c0", doc_id, f"{doc_id}.pdf",
                          "Flange gaskets shall be spiral wound with a graphite filler.",
                          f"h-{doc_id}"))
    for doc_id in ("ok", "bad"):
        keyword.index_document(doc_id)
    _add_vectors([_vector("ok-c0", "ok"), _vector("bad-c0", "bad")])
    return frozenset({"ok", "bad"})


def test_search_never_returns_a_chunk_of_a_failed_document():
    scope = _two_documents()
    hits = keyword.search("spiral wound gaskets", limit=10, allowed_document_ids=scope)
    assert [h["chunk_id"] for h in hits] == ["ok-c0"]
    dense = vector_store.search(lambda: np.ones(EMBEDDING_DIM, dtype="float32"),
                                limit=10, allowed_document_ids=scope)
    assert [h["chunk_id"] for h in dense] == ["ok-c0"]


def test_a_document_being_re_processed_keeps_answering_from_its_last_build():
    scope = _two_documents()
    with connect() as conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = 'bad'", (states.CHUNKING,))
    hits = keyword.search("spiral wound gaskets", limit=10, allowed_document_ids=scope)
    assert {h["chunk_id"] for h in hits} == {"ok-c0", "bad-c0"}


# ================================= 4. finishing touches ingestion jobs only

def test_finishing_a_document_leaves_its_other_jobs_alone():
    _partial_document()
    _add_vectors([_vector("p1-b", "p1")])
    with connect() as conn:
        conn.executemany("""INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)
                            VALUES (?, 'p1', ?, ?, ?, ?)""",
                         [("j-ingest", "chunk", "running", NOW, NOW),
                          ("j-facts", "extract_facts", "failed", NOW, NOW),
                          ("j-reqs", "extract_requirements", "queued", NOW, NOW)])
    IngestionWorker()._finish_if_embedded("p1")
    states_by_job = {r[0]: r[1] for r in connect().execute("SELECT id, state FROM jobs")}
    assert connect().execute(
        "SELECT status FROM documents WHERE id = 'p1'").fetchone()[0] == states.READY
    assert states_by_job["j-ingest"] == "done"
    assert states_by_job["j-facts"] == "failed"
    assert states_by_job["j-reqs"] == "queued"
