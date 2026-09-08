"""FTS-first ordering: a document must be answerable before it is embedded."""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical, states
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

    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) == 0
    assert keyword.search("vibration limit API 610", allowed_document_ids=_scope()) == []


def test_reindexing_replaces_rather_than_duplicates():
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)

    first = keyword.index_document(doc_id)["indexed"]
    keyword.index_document(doc_id)
    keyword.index_document(doc_id)
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) == first


def test_rechunking_invalidates_the_index():
    """The index is keyed on chunk ids, which a rebuild regenerates."""
    client = TestClient(app)
    doc_id = upload(client)
    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) > 0

    chunk_document(doc_id, force=True)
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) == 0, "stale index survived a rebuild"


def test_deleting_a_document_removes_it_from_the_index():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) > 0

    TestClient(app).delete(f"/api/documents/{doc_id}?confirm=true")
    assert keyword.indexed_count(doc_id, allowed_document_ids=_scope()) == 0


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


# ------------------------------------------------- the presence oracle (F3)


SECRET = [
    "12.1 Inconel Cladding",
    "Inconel 625 weld overlay shall be applied to the sealing faces of every",
    "subsea connector supplied under this specification before delivery.",
]


def _index(client, name, blocks) -> str:
    doc_id = upload(client, name=name, blocks=blocks)
    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)
    return doc_id


def test_a_term_only_in_an_unreadable_document_counts_as_absent():
    """The lexical gate must not be a presence oracle.

    `term_occurrences` and `indexed_count` took no scope at all: they counted
    over the whole `chunks_fts` table. So the gate's verdict - and the
    user-visible refusal "none of the terms in this question appear in the
    indexed documents" - was decided partly by documents the caller has no
    grant on. A caller could tell that "Inconel" exists in the corpus by the
    system declining to say it does not, which is the same disclosure
    `/api/health` was stripped for.

    MUTATION-PROVEN. Drop the scope predicate from `term_occurrences` and the
    restricted caller sees a non-zero count for a document they cannot read.
    """
    client = TestClient(app)
    readable = _index(client, "readable.pdf", (SPEC,))
    _index(client, "secret.pdf", (SECRET,))

    mine = frozenset({readable})

    # Corpus-wide the term really is there, so the assertion below is about
    # SCOPE, not about the term being missing from the whole corpus.
    assert keyword.term_occurrences(
        "Inconel", allowed_document_ids=_scope()) > 0, "precondition"

    assert keyword.term_occurrences("Inconel", allowed_document_ids=mine) == 0, (
        "a caller learned that a term exists in a document they may not read")

    # The denominator the gate judges commonness against is the caller's
    # corpus too, not everybody's.
    assert (keyword.indexed_count(allowed_document_ids=mine)
            < keyword.indexed_count(allowed_document_ids=_scope()))

    # NOT VACUOUS: a term that IS in the readable document still counts.
    assert keyword.term_occurrences(
        "vibration", allowed_document_ids=mine) > 0


def test_an_empty_scope_counts_nothing_rather_than_everything():
    """Zero grants is a real answer and must not fall through to the whole
    corpus. `indexed_count` returning 0 makes `lexical.assess` abstain, which
    is the safe direction: it never becomes a claim that a term is absent.
    """
    client = TestClient(app)
    _index(client, "readable.pdf", (SPEC,))

    assert keyword.indexed_count(allowed_document_ids=frozenset()) == 0
    assert keyword.term_occurrences(
        "vibration", allowed_document_ids=frozenset()) == 0

    verdict = lexical.assess(
        "what is the vibration limit", "any text at all",
        allowed_document_ids=frozenset())
    assert verdict["ok"] is True, "an empty scope must abstain, not refuse"
    assert verdict["absent_from_corpus"] == [], (
        "a caller with no grants was told a term is absent from a corpus they "
        "cannot see any of")


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
