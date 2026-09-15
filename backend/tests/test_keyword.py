"""FTS-first ordering: a document must be answerable before it is embedded."""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, states
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.ingest import IngestionWorker
from app.main import app

SPEC = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during normal operation at rated flow.",
    "Casing material shall be ASTM A216 WCB and the shaft AISI 4140 throughout.",
    "Any exceedance shall be reported to the area engineer before returning the",
    "pump to service under the maintenance procedure described in this section.",
]

OTHER = [
    "7.1 Coating Systems",
    "External surfaces shall be prepared to a near-white metal finish and coated",
    "with a two part epoxy primer followed by a polyurethane topcoat as specified",
    "in the painting schedule appended to this document for offshore service.",
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


def make_pdf(path, blocks):
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def upload(client, name="spec.pdf", blocks=(SPEC, OTHER)) -> str:
    path = make_pdf(settings.data_dir / name, blocks)
    with open(path, "rb") as fh:
        return client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]


# ------------------------------------------------------------- tokenisation


def test_identifiers_survive_tokenisation():
    """The default tokenizer splits 5.3.2 into three tokens, destroying exactly
    the lookups lexical search exists to get right."""
    q = keyword.build_match_query("what is clause 5.3.2 of API 610")
    assert '"5.3.2"' in q
    assert '"API 610"' in q or '"610"' in q


def test_identifiers_are_required_not_merely_preferred():
    """A question naming API 610 is asking about API 610."""
    q = keyword.build_match_query("vibration limit per API 610")
    assert " AND " in q, f"identifier was not required: {q}"


def test_a_question_with_no_usable_tokens_returns_nothing_rather_than_erroring():
    assert keyword.build_match_query("?? !!") == ""
    assert keyword.search("?? !!", allowed_document_ids=_scope()) == []


def test_conversational_stopwords_do_not_enter_the_match_query():
    q = keyword.build_match_query("can you tell me about Design team leader")
    assert q == '("Design" OR "team" OR "leader")'


def test_exact_content_phrase_is_built_separately_from_the_recall_query():
    assert keyword.build_phrase_query(
        "can you tell me about Design team leader"
    ) == '"Design team leader"'


def test_exact_glossary_phrase_outranks_repeated_scattered_words():
    conn = db.connect()
    conn.executemany(
        """INSERT INTO chunks_fts
           (text, section, filename, chunk_id, document_id)
           VALUES (?, ?, 'doc16.pdf', ?, 'doc16')""",
        [
            (
                "The design team will deploy the dataset. Design reviews help "
                "the team, and design work is shared by team leaders.",
                "Deployment", "scattered",
            ),
            (
                "Design Team Leader (DTL) - Engineer or Architect responsible "
                "for coordinating the efforts of all modelers and technicians.",
                "Glossary", "glossary",
            ),
        ],
    )
    conn.commit()

    hits = keyword.search(
        "can you tell me about Design team leader",
        allowed_document_ids=frozenset({"doc16"}),
    )
    assert [hit["chunk_id"] for hit in hits[:2]] == ["glossary", "scattered"]


def test_a_malformed_query_does_not_raise():
    # FTS5 treats several characters as syntax; every token is quoted
    assert isinstance(keyword.search('AND OR NOT " ( )', allowed_document_ids=_scope()), list)


# ------------------------------------------------------- ordering guarantee


def test_a_document_is_searchable_before_a_single_vector_exists():
    """The whole point of FTS-first: answerable seconds after upload, while
    embedding is still running."""
    client = TestClient(app)
    doc_id = upload(client)

    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)

    vectors = db.connect().execute(
        "SELECT COUNT(*) FROM chunk_vectors WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    assert vectors == 0, "this test is meaningless if embedding already ran"

    hits = keyword.search("API 610 vibration limit", allowed_document_ids=_scope())
    assert hits, "keyword search returned nothing without vectors"
    assert hits[0]["document_id"] == doc_id


def test_the_worker_indexes_keywords_before_it_embeds():
    """Ordering is a property of the pipeline, not of how it happens to be
    called. Asserted from the stage sequence the worker reports."""
    client = TestClient(app)
    doc_id = upload(client)
    result = IngestionWorker().process(doc_id)

    stages = result["stages"]
    assert "keyword_index" in stages, stages
    assert "embed" in stages, stages
    assert stages.index("keyword_index") < stages.index("embed"), (
        f"embedding ran before the keyword index: {stages}"
    )


def test_the_document_becomes_answerable_at_the_indexing_stage():
    client = TestClient(app)
    doc_id = upload(client)
    worker = IngestionWorker()

    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)
    worker._set_state(doc_id, states.PARTIALLY_SEARCHABLE)

    status = db.connect().execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()["status"]
    assert states.is_answerable(status)
    assert keyword.search("vibration limit", allowed_document_ids=_scope())


# --------------------------------------------------------------- exclusions


def test_search_never_returns_a_non_retrievable_chunk():
    """Enforced at index time rather than relying on every query to filter."""
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)

    conn = db.connect()
    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE document_id = ?", (doc_id,))
    keyword.index_document(doc_id)

    assert keyword.indexed_count(doc_id) == 0
    assert keyword.search("vibration limit API 610", allowed_document_ids=_scope()) == []


def test_reindexing_replaces_rather_than_duplicates():
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)

    first = keyword.index_document(doc_id)["indexed"]
    keyword.index_document(doc_id)
    keyword.index_document(doc_id)
    assert keyword.indexed_count(doc_id) == first


def test_rechunking_invalidates_the_index():
    """The index is keyed on chunk ids, which a rebuild regenerates."""
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)
    assert keyword.indexed_count(doc_id) > 0

    chunk_document(doc_id, force=True)
    assert keyword.indexed_count(doc_id) == 0, "stale index survived a rebuild"


def test_deleting_a_document_removes_it_from_the_index():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)
    assert keyword.indexed_count(doc_id) > 0

    TestClient(app).delete(f"/api/documents/{doc_id}?confirm=true")
    assert keyword.indexed_count(doc_id) == 0


# ---------------------------------------------------------------- endpoint


def test_the_search_endpoint_returns_pages_and_text():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    r = client.get("/api/search?q=API 610 vibration limit&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0
    hit = body["hits"][0]
    assert hit["document_id"] == doc_id
    assert hit["page_start"] >= 1
    assert "API 610" in hit["text"] or "vibration" in hit["text"].lower()


def test_search_rejects_unknown_parameters_and_bad_limits():
    client = TestClient(app)
    assert client.get("/api/search?q=x&bogus=1").status_code == 422
    assert client.get("/api/search?q=x&limit=0").status_code == 422
    assert client.get("/api/search?q=x&limit=99999").status_code == 422
    assert client.get("/api/search?q=").status_code == 422


def test_search_can_be_scoped_to_one_document():
    client = TestClient(app)
    a = upload(client, "a.pdf", (SPEC,))
    b = upload(client, "b.pdf", (OTHER,))
    worker = IngestionWorker()
    worker.process(a)
    worker.process(b)

    r = client.get(f"/api/search?q=coating epoxy primer&document_id={b}").json()
    assert r["total"] > 0
    assert all(h["document_id"] == b for h in r["hits"])

    assert client.get("/api/search?q=x&document_id=doc_zzzzzzzzzzzz").status_code == 404


def _scope():
    """Corpus-wide scope, stated explicitly.

    Retrieval now REQUIRES an access scope with no default, so a test has to
    name the documents it is allowed to see. These tests want all of them, and
    saying so out loud is the point: when authentication arrives, every one of
    these is a line somebody changes on purpose rather than a default that
    quietly kept meaning "everything".
    """
    from app.search import every_document_id
    return every_document_id()
