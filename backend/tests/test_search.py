"""Hybrid retrieval: RRF fusion, identifier boosting, dedup, reranking."""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, reranker, search
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow,",
    "and any exceedance shall be reported to the area engineer before the pump",
    "is returned to service under the procedure given in this specification.",
]

MATERIALS = [
    "7.1 Materials of Construction",
    "Casing material shall be ASTM A216 WCB with an impeller of CA6NM and a",
    "shaft of AISI 4140 for all centrifugal pumps in hydrocarbon service, and",
    "alternative materials require written approval from the principal engineer",
    "before any substitution is made during fabrication or later maintenance.",
]

COATING = [
    "9.4 Coating Systems",
    "External surfaces shall be prepared to a near-white metal finish and then",
    "coated with a two part epoxy primer followed by a polyurethane topcoat as",
    "described in the painting schedule appended to this document, for all",
    "equipment installed in offshore or coastal environments.",
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


def build(path, blocks):
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def upload(client, name="spec.pdf", blocks=(VIBRATION, MATERIALS, COATING)) -> str:
    path = build(settings.data_dir / name, blocks)
    with open(path, "rb") as fh:
        return client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]


# ------------------------------------------------------------------- RRF


def test_rrf_fuses_ranks_not_scores():
    """BM25 and cosine are not comparable - different scales and signs. RRF
    discards the magnitudes and fuses the RANKS."""
    kw = [{"chunk_id": "a", "bm25": -30.0}, {"chunk_id": "b", "bm25": -10.0}]
    dn = [{"chunk_id": "b", "cosine": 0.9}, {"chunk_id": "c", "cosine": 0.8}]
    fused = search.rrf_fuse(kw, dn, k=60)

    # b appears in both lists, so it must outrank items found by one side only
    assert fused["b"]["rrf"] > fused["a"]["rrf"]
    assert fused["b"]["rrf"] > fused["c"]["rrf"]
    assert fused["a"]["keyword_rank"] == 1 and "dense_rank" not in fused["a"]
    assert fused["c"]["dense_rank"] == 2 and "keyword_rank" not in fused["c"]


def test_rrf_handles_an_empty_dense_list():
    """The normal case before embedding finishes."""
    kw = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    fused = search.rrf_fuse(kw, [], k=60)
    assert set(fused) == {"a", "b"}
    assert fused["a"]["rrf"] > fused["b"]["rrf"]


# ------------------------------------------------------- identifier boost


PETROLEUM_IDENTIFIERS = [
    ("vibration limits per API 610", "API 610"),
    ("casing shall be ASTM A216 WCB", "ASTM A216"),
    ("per NORSOK L-001 section", "NORSOK L-001"),
    ("NORSOK M-501 coating system", "NORSOK M-501"),
    ("as defined in ISO 13709", "ISO 13709"),
    ("shaft of AISI 4140 steel", "AISI 4140"),
    ("impeller of CA6NM material", "CA6NM"),
    ("pump P-101A is offline", "P-101A"),
    ("clause 5.3.2 applies", "5.3.2"),
]


@pytest.mark.parametrize("question,expected", PETROLEUM_IDENTIFIERS)
def test_identifiers_used_in_petroleum_standards_are_extracted(question, expected):
    """Each of these is a real convention in an oil and gas specification, and
    a missed one is a lookup that silently returns the wrong passage. An
    earlier pattern required letters immediately followed by digits, so it
    matched API 610 but missed ASTM A216 and NORSOK L-001 entirely."""
    found = search.find_identifiers(question)
    assert expected in found, f"{expected!r} not extracted from {question!r}: {found}"


def test_ordinary_prose_yields_no_identifiers():
    assert search.find_identifiers("what is the coating procedure") == []


def test_a_chunk_naming_the_identifier_is_boosted_above_one_that_does_not():
    """A question about API 610 is about API 610. Semantic similarity will
    happily rank a general passage about vibration above the one that names
    the standard, which is the wrong answer for an engineering lookup."""
    named = search.Candidate(
        chunk_id="named", document_id="d", filename="f", section=None,
        page_start=1, page_end=1,
        text="Vibration limits per API 610 shall not exceed 3.0 mm/s RMS.",
        rrf=0.010,
    )
    unnamed = search.Candidate(
        chunk_id="unnamed", document_id="d", filename="f", section=None,
        page_start=2, page_end=2,
        text="Vibration should generally be kept low on rotating equipment.",
        rrf=0.012,  # deliberately the better RRF score
    )
    pool = [named, unnamed]
    search.apply_identifier_boost("what does API 610 say about vibration", pool)

    assert named.identifier_hits, "the identifier was not detected in the chunk"
    assert not unnamed.identifier_hits
    assert named.score > unnamed.score, "the passage naming the standard did not win"


def test_no_boost_is_applied_when_the_question_has_no_identifier():
    c = search.Candidate(
        chunk_id="x", document_id="d", filename="f", section=None,
        page_start=1, page_end=1, text="API 610 mentioned here", rrf=0.01,
    )
    search.apply_identifier_boost("how do I coat a surface", [c])
    assert c.boost == 0.0


# ------------------------------------------------------------ duplicates


def test_near_identical_chunks_are_deduplicated():
    body = " ".join(f"word{i}" for i in range(60))
    a = search.Candidate("a", "d", "f", None, 1, 1, body, rrf=0.02)
    b = search.Candidate("b", "d", "f", None, 2, 2, body + " word60", rrf=0.01)
    c = search.Candidate("c", "d", "f", None, 3, 3, "completely different text here", rrf=0.005)

    kept = search.deduplicate([a, b, c])
    ids = {x.chunk_id for x in kept}
    assert "a" in ids, "the better-scoring duplicate should survive"
    assert "b" not in ids, "a near-identical chunk was not removed"
    assert "c" in ids


# ------------------------------------------------ degradation and upgrade


def test_search_works_keyword_only_before_any_vector_exists():
    client = TestClient(app)
    doc_id = upload(client)
    from app.chunker import chunk_document
    from app.extract import extract_document

    extract_document(doc_id)
    chunk_document(doc_id)
    keyword.index_document(doc_id)

    vectors = db.connect().execute(
        "SELECT COUNT(*) FROM chunk_vectors WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    assert vectors == 0

    result = search.search("vibration limits API 610", limit=5)
    assert result["mode"] == "keyword_only"
    assert result["dense_candidates"] == 0
    assert result["total"] > 0, "keyword-only retrieval returned nothing"


def test_search_upgrades_to_hybrid_once_vectors_arrive():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    result = search.search("vibration limits API 610", limit=5)
    assert result["mode"] == "hybrid"
    assert result["dense_candidates"] > 0
    assert result["total"] > 0


def test_dense_search_returns_nothing_rather_than_failing_with_no_vectors():
    assert search.dense_search("anything at all") == []


# --------------------------------------------------------------- safety


def test_search_never_returns_a_non_retrievable_chunk():
    client = TestClient(app)
    doc_id = upload(client)
    worker = IngestionWorker()
    worker.process(doc_id)
    assert search.search("vibration limits", limit=10)["total"] > 0

    conn = db.connect()
    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE document_id = ?", (doc_id,))
    keyword.index_document(doc_id)

    result = search.search("vibration limits API 610", limit=10)
    assert result["total"] == 0, "an excluded chunk came back through search"


def test_a_vector_orphaned_by_rechunking_cannot_be_retrieved():
    """Dense retrieval joins against chunks, so a stale vector is invisible."""
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
    assert search.dense_search("vibration limits") == []


# --------------------------------------------------------------- reranker


@pytest.mark.skipif(not reranker.available(), reason="reranker model not staged")
def test_the_reranker_scores_a_relevant_passage_above_an_irrelevant_one():
    pairs = [
        ("irrelevant", "The painting schedule lists epoxy primer for offshore use."),
        ("relevant", "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS."),
    ]
    scores = dict(reranker.rerank("what is the vibration limit for a pump", pairs))
    assert scores["relevant"] > scores["irrelevant"]


def test_retrieval_still_works_when_the_reranker_is_unavailable():
    """Reranking is an enhancement, never a dependency."""
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    result = search.search("vibration limits API 610", limit=5, rerank=False)
    assert result["reranked"] is False
    assert result["total"] > 0
    assert all(h["rerank_score"] is None for h in result["hits"])


# --------------------------------------------------------------- endpoint


def test_the_search_endpoint_reports_which_mode_it_used():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    body = client.get("/api/search?q=vibration limits API 610&limit=5").json()
    assert body["mode"] in ("hybrid", "keyword_only")
    assert body["total"] > 0
    hit = body["hits"][0]
    assert hit["page_start"] >= 1
    assert "timings" in body

    forced = client.get("/api/search?q=vibration limits&mode=keyword").json()
    assert forced["mode"] == "keyword_only"
    assert forced["dense_candidates"] == 0


def test_the_search_endpoint_validates_its_parameters():
    client = TestClient(app)
    assert client.get("/api/search?q=x&mode=telepathy").status_code == 422
    assert client.get("/api/search?q=x&bogus=1").status_code == 422
    assert client.get("/api/search?q=x&limit=0").status_code == 422
    assert client.get("/api/search?q=x&document_id=doc_zzzzzzzzzzzz").status_code == 404
