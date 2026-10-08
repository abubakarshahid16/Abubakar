"""Hybrid retrieval: RRF fusion, identifier boosting, dedup, reranking."""

import pymupdf
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
    doc = pymupdf.open()
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


def test_an_exact_multiword_content_phrase_uses_the_existing_lexical_boost():
    exact = search.Candidate(
        chunk_id="exact", document_id="d", filename="doc16.pdf", section="Glossary",
        page_start=14, page_end=14,
        text="Design Team Leader (DTL) - Engineer responsible for coordinating modelers.",
        rrf=0.010,
    )
    scattered = search.Candidate(
        chunk_id="scattered", document_id="d", filename="doc16.pdf", section=None,
        page_start=12, page_end=12,
        text="The design team deploys data; design reviews involve team leaders.",
        rrf=0.012,
    )
    search.apply_identifier_boost(
        "can you tell me about Design team leader", [exact, scattered]
    )

    assert exact.phrase_hits == ["design team leader"]
    assert scattered.phrase_hits == []
    assert exact.score > scattered.score


def test_a_requested_decimal_row_key_beats_the_table_heading():
    """Table questions must retrieve the row containing the requested value.

    A reranker naturally prefers a general section heading such as ``WAVE
    EQUATION``.  When the user asks for time ``4.00``, the passage containing
    that exact decimal is the useful evidence and must win.
    """
    row = search.Candidate(
        chunk_id="row", document_id="d", filename="book2.pdf", section="15.3 WAVE EQUATION",
        page_start=597, page_end=597, text="Time 4.00 25.6452 29.6517", rrf=0.010,
        rerank_score=0.45,
    )
    heading = search.Candidate(
        chunk_id="heading", document_id="d", filename="book2.pdf", section="15.3 WAVE EQUATION",
        page_start=546, page_end=546, text="TABLE 15.7 Actual Approx.", rrf=0.012,
        rerank_score=1.80,
    )
    search.apply_identifier_boost(
        "In the wave equation table, what value is listed at time 4.00?",
        [row, heading],
    )
    assert row.numeric_hits == ["4.00"]
    # The search pipeline adds ``boost`` to the reranker score immediately
    # after the cross-encoder returns it.
    assert row.boost > (heading.rerank_score - row.rerank_score)


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

    result = search.search("vibration limits API 610", limit=5, allowed_document_ids=_scope())
    assert result["mode"] == "keyword_only"
    assert result["dense_candidates"] == 0
    assert result["total"] > 0, "keyword-only retrieval returned nothing"


def test_search_upgrades_to_hybrid_once_vectors_arrive():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    result = search.search("vibration limits API 610", limit=5, allowed_document_ids=_scope())
    assert result["mode"] == "hybrid"
    assert result["dense_candidates"] > 0
    assert result["total"] > 0


def test_dense_search_returns_nothing_rather_than_failing_with_no_vectors():
    assert search.dense_search("anything at all", allowed_document_ids=_scope()) == []


# --------------------------------------------------------------- safety


def test_search_never_returns_a_non_retrievable_chunk():
    client = TestClient(app)
    doc_id = upload(client)
    worker = IngestionWorker()
    worker.process(doc_id)
    assert search.search("vibration limits", limit=10, allowed_document_ids=_scope())["total"] > 0

    conn = db.connect()
    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE document_id = ?", (doc_id,))
    keyword.index_document(doc_id)

    result = search.search("vibration limits API 610", limit=10, allowed_document_ids=_scope())
    assert result["total"] == 0, "an excluded chunk came back through search"


def test_a_vector_orphaned_by_rechunking_cannot_be_retrieved():
    """Dense retrieval joins against chunks, so a stale vector is invisible."""
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
    assert search.dense_search("vibration limits", allowed_document_ids=_scope()) == []


# --------------------------------------------------------------- reranker


def test_a_short_factual_question_is_sent_to_the_reranker(monkeypatch):
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)
    calls = []

    def record(question, pairs):
        calls.append((question, pairs))
        return [(chunk_id, 1.0) for chunk_id, _ in pairs]

    monkeypatch.setattr(reranker, "rerank", record)
    result = search.search(
        "Vibration limit?", limit=5,
        allowed_document_ids=frozenset({doc_id}),
    )

    assert calls, "short factual questions bypassed the cross-encoder"
    assert result["reranked"] is True


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

    result = search.search("vibration limits API 610", limit=5, rerank=False, allowed_document_ids=_scope())
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


# ------------------------------------------------------- the access scope
#
# These are the negative tests for the scope parameter. They contain no
# authentication - authentication does not exist yet. They assert the one
# property everything above it will depend on: a document outside the scope is
# not reachable through EITHER retrieval path.


def test_the_keyword_path_cannot_reach_a_document_outside_the_scope():
    client = TestClient(app)
    visible = upload(client, "visible.pdf")
    hidden = upload(client, "hidden.pdf")
    for d in (visible, hidden):
        IngestionWorker().process(d)

    # Scope names ONE document. The other must be unreachable, not merely
    # absent from the top of the list.
    result = search.search(
        "vibration limits API 610", limit=50, dense=False, rerank=False,
        allowed_document_ids=frozenset({visible}),
    )
    got = {h["document_id"] for h in result["hits"]}
    assert got == {visible}, f"keyword path leaked {got - {visible}}"
    assert result["hits"], "scoped search returned nothing at all"


def test_the_dense_path_cannot_reach_a_document_outside_the_scope():
    client = TestClient(app)
    visible = upload(client, "visible.pdf")
    hidden = upload(client, "hidden.pdf")
    for d in (visible, hidden):
        IngestionWorker().process(d)

    vectors = db.connect().execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    assert vectors > 0, "no vectors: this test would pass vacuously"

    result = search.search(
        "vibration limits API 610", limit=50, dense=True, rerank=False,
        allowed_document_ids=frozenset({visible}),
    )
    got = {h["document_id"] for h in result["hits"]}
    assert got == {visible}, f"dense path leaked {got - {visible}}"
    assert result["dense_candidates"] > 0, "dense side did not run"


def test_an_empty_scope_returns_nothing_rather_than_everything():
    """The failure mode this parameter exists to prevent. An empty scope is a
    real answer - this caller may see nothing - and must never be read as
    'unfiltered'."""
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    result = search.search(
        "vibration limits API 610", limit=50,
        allowed_document_ids=frozenset(),
    )
    assert result["hits"] == []
    assert result["total"] == 0


def test_filtering_happens_before_selection_not_after():
    """Discarding results after top-k is not access control.

    If an out-of-scope chunk consumed a candidate slot and were dropped
    afterwards, an authorised chunk would be pushed out of the result - so the
    caller would get FEWER results because of a document they are not allowed
    to know exists. Scoping to one document must return as many hits as asking
    that document directly.
    """
    client = TestClient(app)
    visible = upload(client, "visible.pdf")
    hidden = upload(client, "hidden.pdf")
    for d in (visible, hidden):
        IngestionWorker().process(d)

    scoped = search.search(
        "vibration limits API 610", limit=10, rerank=False,
        allowed_document_ids=frozenset({visible}),
    )
    direct = search.search(
        "vibration limits API 610", limit=10, rerank=False,
        document_id=visible, allowed_document_ids=frozenset({visible}),
    )
    assert len(scoped["hits"]) == len(direct["hits"]), (
        "scoped search returned fewer hits than the same document asked "
        "directly - out-of-scope rows are consuming candidate slots"
    )


# ------------------------------------------------------ accounting for drops


def test_a_displaced_candidate_is_recorded_with_a_reason(monkeypatch):
    """The pipeline's one unaccounted loss.

    Candidates ranked below the shortlist cut were dropped with nothing said
    about it, which made two very different situations identical in the
    response: a document that matched nothing, and a document that contributed
    candidates and had every one of them displaced. Any coverage claim built on
    the second reading would have been wrong, with no way to tell from the
    result which reading applied.
    """
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(settings, "rerank_candidates", 2)
    monkeypatch.setattr(
        reranker, "rerank", lambda q, pairs: [(cid, -1.0) for cid, _ in pairs]
    )

    result = search.search(
        "vibration materials coating", limit=10, allowed_document_ids=_scope()
    )
    assert result["reranked"] is True
    assert result["total"] == 2, "the shortlist cut did not apply"

    displaced = [
        e for e in result["shortlist_excluded"]
        if e["reason"] == "displaced_before_rerank"
    ]
    assert displaced, "candidates were cut from the shortlist with no record"
    assert all(e["document_id"] == doc_id for e in displaced)
    assert all(e["rrf"] is not None for e in displaced), (
        "the score it was cut on is the whole point of the record"
    )


def test_a_document_that_wins_nothing_is_distinguishable_from_one_that_matched_nothing(
    monkeypatch,
):
    """The question this telemetry exists to answer, in miniature.

    Gold question Q4 is answered from one document while a second carries the
    same terms. Whether the second was ever in the pool decides whether the
    fix is a retrieval change or a reporting one - and before this record there
    was no way to find out short of instrumenting a local build.
    """
    client = TestClient(app)
    winner = upload(client, name="a.pdf", blocks=(VIBRATION, MATERIALS))
    loser = upload(client, name="b.pdf", blocks=(COATING,))
    worker = IngestionWorker()
    worker.process(winner)
    worker.process(loser)

    monkeypatch.setattr(settings, "rerank_candidates", 1)
    monkeypatch.setattr(
        reranker, "rerank", lambda q, pairs: [(cid, -1.0) for cid, _ in pairs]
    )

    result = search.search(
        "vibration limits and coating systems",
        limit=10,
        allowed_document_ids=frozenset({winner, loser}),
    )
    answered = {h["document_id"] for h in result["hits"]}
    recorded = {e["document_id"] for e in result["shortlist_excluded"]}

    assert len(answered) == 1, "the cut should have left one document answering"
    absent = ({winner, loser} - answered).pop()
    assert absent in recorded, (
        "a document contributed candidates, lost all of them, and the result "
        "looked exactly like a document that matched nothing"
    )


def test_a_near_duplicate_is_recorded_rather_than_vanishing():
    body = " ".join(f"word{i}" for i in range(60))
    a = search.Candidate("a", "d", "f", None, 1, 1, body, rrf=0.02)
    b = search.Candidate("b", "d", "f", None, 2, 2, body + " word60", rrf=0.01)
    dropped: list[dict] = []

    kept = search.deduplicate([a, b], dropped)

    assert [x.chunk_id for x in kept] == ["a"]
    assert dropped == [
        # B6C: and WHICH kept chunk it repeats, so a copy in another document
        # can be reported as an ambiguous source
        {"chunk_id": "b", "document_id": "d", "rrf": 0.01, "reason": "near_duplicate",
         "duplicate_of": "a"}
    ]


def test_dedup_without_a_record_still_returns_a_plain_list():
    """The out-parameter is optional: one caller wants it, the tests do not."""
    body = " ".join(f"word{i}" for i in range(60))
    a = search.Candidate("a", "d", "f", None, 1, 1, body, rrf=0.02)
    b = search.Candidate("b", "d", "f", None, 2, 2, body, rrf=0.01)
    assert [x.chunk_id for x in search.deduplicate([a, b])] == ["a"]


def test_the_unreranked_path_reports_no_displacement():
    """`eval/reachability.py` runs with rerank=False.

    Nothing is cut on that path, so nothing may be reported as cut. A sweep
    that started seeing evictions would be measuring a different thing.
    """
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    result = search.search(
        "vibration materials coating", limit=2, rerank=False,
        allowed_document_ids=_scope(),
    )
    assert result["reranked"] is False
    assert not [
        e for e in result["shortlist_excluded"]
        if e["reason"] == "displaced_before_rerank"
    ]


def test_a_candidate_is_never_both_returned_and_reported_as_dropped(monkeypatch):
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(settings, "rerank_candidates", 2)
    monkeypatch.setattr(
        reranker, "rerank", lambda q, pairs: [(cid, -1.0) for cid, _ in pairs]
    )

    result = search.search(
        "vibration materials coating", limit=10, allowed_document_ids=_scope()
    )
    returned = {h["chunk_id"] for h in result["hits"]}
    dropped = {e["chunk_id"] for e in result["shortlist_excluded"]}
    assert not (returned & dropped)
    assert all(e["reason"] in search.EVICTION_REASONS for e in result["shortlist_excluded"])


def test_a_shortlist_record_is_discarded_when_the_reranker_produces_nothing(monkeypatch):
    """The cut is recorded before the rerank runs, so it has to be conditional.

    If the reranker returns nothing the pool is left whole - those candidates
    were never dropped, and reporting them as dropped would be a lie about a
    path that is exercised every time the model is unavailable.
    """
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(settings, "rerank_candidates", 1)
    monkeypatch.setattr(reranker, "rerank", lambda q, pairs: [])

    result = search.search(
        "vibration materials coating", limit=10, allowed_document_ids=_scope()
    )
    assert result["reranked"] is False
    assert result["total"] > 1, "the pool should have been left whole"
    assert not [
        e for e in result["shortlist_excluded"]
        if e["reason"] == "displaced_before_rerank"
    ]
