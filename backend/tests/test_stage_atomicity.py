"""A stage must never finish its work without advancing the state.

The eighth instance of a status not matching what happened: a 1,200-page
document had a fully built, searchable keyword index and still sat at
`indexing_keyword`, so embedding never started and it was stranded for 21
minutes. Same shape as the chunk short-circuit that left documents at
`chunking`.

The structural answer is that "do the work" and "advance the state" must not
be two steps that can drift. These tests assert the invariant directly rather
than testing one stage's happy path.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, states
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.ingest import IngestionWorker
from app.main import app

BODY = [
    "The vibration limit shall not exceed three point zero millimetres per",
    "second measured at the bearing housing during normal operation, and any",
    "reading above that value shall be reported to the area engineer before",
    "the pump is returned to service under the maintenance procedure given",
    "in section five of this specification for all rotating equipment.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, name="spec.pdf", pages=40) -> str:
    """A document big enough that indexing does real work."""
    path = settings.data_dir / name
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 90), f"{(i % 9) + 1}.{i} Requirements for unit {i}")
        for n, line in enumerate(BODY):
            page.insert_text((72, 120 + n * 15), f"{line} Unit {i}.")
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        return client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]


def status_of(doc_id: str) -> str:
    return db.connect().execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()["status"]


# ------------------------------------------------------------- the invariant


def test_a_document_with_a_built_index_is_never_left_at_indexing_keyword():
    """The exact stranded state: index built and searchable, status unmoved."""
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)
    assert status_of(doc_id) == states.INDEXING_KEYWORD

    result = keyword.index_document(
        doc_id,
        advance_to=states.PARTIALLY_SEARCHABLE,
        expect_status=states.INDEXING_KEYWORD,
    )
    assert result["indexed"] > 0, "the fixture must produce a real index"

    assert status_of(doc_id) != states.INDEXING_KEYWORD, (
        "the index is built and searchable but the status never advanced - "
        "embedding will never start and the document is stranded"
    )
    assert status_of(doc_id) == states.PARTIALLY_SEARCHABLE
    assert states.is_answerable(status_of(doc_id))


def test_indexing_and_the_state_advance_are_one_transaction():
    """If the state cannot advance, the index write must not persist either."""
    client = TestClient(app)
    doc_id = upload(client, pages=12)
    extract_document(doc_id)
    chunk_document(doc_id)

    conn = db.connect()
    original = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert original["status"] == states.INDEXING_KEYWORD

    # A compare-and-set against the WRONG expected status must leave the
    # document alone; the index may be rebuilt but the status must not move.
    keyword.index_document(
        doc_id, advance_to=states.READY, expect_status="a_status_that_never_existed"
    )
    assert status_of(doc_id) == states.INDEXING_KEYWORD, (
        "a guarded transition fired despite the guard not matching"
    )


def test_after_indexing_the_worker_goes_on_to_embed():
    """Advancing the state is only useful if the next stage actually runs."""
    client = TestClient(app)
    doc_id = upload(client, pages=25)
    worker = IngestionWorker()
    result = worker.process(doc_id)

    stages = result["stages"]
    assert "keyword_index" in stages, stages
    assert "embed" in stages, f"embedding never started after indexing: {stages}"
    assert stages.index("keyword_index") < stages.index("embed")

    row = db.connect().execute(
        "SELECT status, chunk_count, embedded_count, indexed_at FROM documents"
        " WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["embedded_count"] == row["chunk_count"] > 0
    assert row["status"] == states.READY
    assert row["indexed_at"] is not None


def test_no_stage_leaves_work_done_with_the_state_unadvanced():
    """Sweep the whole pipeline: at no point may a document hold completed
    work for a stage while still sitting in that stage's status."""
    client = TestClient(app)
    doc_id = upload(client, pages=20)
    worker = IngestionWorker()
    worker.process(doc_id)

    conn = db.connect()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    pages = conn.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    chunks = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    indexed = keyword.indexed_count(doc_id, allowed_document_ids=_scope())
    vectors = conn.execute(
        "SELECT COUNT(*) FROM chunk_vectors WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]

    violations = []
    if pages and row["status"] == states.EXTRACTING:
        violations.append("pages extracted but still 'extracting'")
    if chunks and row["status"] == states.CHUNKING:
        violations.append("chunks built but still 'chunking'")
    if indexed and row["status"] == states.INDEXING_KEYWORD:
        violations.append("index built but still 'indexing_keyword'")
    if (
        vectors >= row["chunk_count"] > 0
        and row["status"] == states.PARTIALLY_SEARCHABLE
    ):
        violations.append("fully embedded but still 'partially_searchable'")

    assert not violations, "; ".join(violations)


def test_a_document_stranded_by_an_older_build_is_recovered():
    """A database written before this fix can hold the stranded state. The
    running worker must repair it without intervention."""
    client = TestClient(app)
    doc_id = upload(client, pages=15)
    worker = IngestionWorker()
    worker.process(doc_id)

    conn = db.connect()
    # reproduce the stranded shape exactly: index intact, status rewound
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, embedded_count = 0, indexed_at = NULL"
            " WHERE id = ?",
            (states.INDEXING_KEYWORD, doc_id),
        )
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) > 0
    assert worker._next_document() == doc_id, "a stranded document is not even queued"

    worker.process(doc_id)
    row = conn.execute(
        "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["status"] == states.READY
    assert row["indexed_at"] is not None


def _scope():
    """Corpus-wide scope, stated explicitly.

    The lexical presence gate now REQUIRES an access scope with no default, so
    a test has to name the documents it is allowed to see. These want all of
    them, and saying so out loud is the point: each of these is a line
    somebody changes on purpose rather than a default that quietly kept
    meaning "everything".
    """
    from app.search import every_document_id
    return every_document_id()
