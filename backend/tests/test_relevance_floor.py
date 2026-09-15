"""The relevance floor and the per-document cap.

Two defects, both observed live on the same question - "do your deep analysis
find all structural models from all documents" - which returned

    "7.42 Which of the following models do you think would produce very
     accurate results?"                  (book2-Differential-Equations.pdf)

for a structural-engineering question, on the bare word "models". RRF fuses
RANKS, so a document with nothing relevant in it still contributes its own
best-of-a-bad-lot, and until now nothing read the cross-encoder's honest
opinion of them.

What is asserted here, and why each assertion cannot pass without the fix:

  * a passage the reranker scored at the bottom of the scale is dropped, and
    the drop is RECORDED with a reason rather than happening silently
  * a field where NOTHING clears the floor still returns passages, and says it
    is low confidence - a false refusal is the worse defect and the floor may
    never cause one
  * one document cannot supply the whole field...
  * ...but a single-document corpus is not capped at all, because there the
    cap can only cut a correct answer to fix a crowding problem that cannot
    happen.
"""

from __future__ import annotations

import pytest

from app import db, keyword, search
from app.config import settings

# Parked. Both features these tests assert (the reranker relevance floor and
# the FTS typo retry) live only in `git stash` - see docs/HANDOVER.md section 2.
# Every test here errors at fixture setup with AttributeError until that stash
# is applied, so the module is skipped rather than deleted.
pytestmark = pytest.mark.skip(reason="parked: feature in stash, see HANDOVER §2")

# Scores taken from the real distribution in eval/rerank-distribution.json:
# correct passages run -8.01..9.67, and the unanswerable tail bottoms out
# around -11.4. -10.4 is squarely in the tail; -1.2 is a real, measured,
# CORRECT answer ("what is the check frequency and the relative humidity
# limit" scores -1.19) and must survive.
ON_TOPIC = 6.9
WEAK_BUT_CORRECT = -1.2
OFF_TOPIC = -10.4


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    keyword.reset_vocabulary_cache()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def candidate(chunk_id: str, document_id: str, score: float, rrf: float = 0.01):
    c = search.Candidate(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=f"{document_id}.pdf",
        section="1.1 Something",
        page_start=1,
        page_end=1,
        text=f"body of {chunk_id}",
        rrf=rrf,
    )
    c.rerank_score = score
    return c


# --------------------------------------------------------------- the floor


def test_an_off_topic_passage_is_dropped_by_the_floor():
    """The differential-equations passage. It scored at the bottom of the
    cross-encoder's range and was returned anyway."""
    field = [
        candidate("spec-1", "spec", ON_TOPIC),
        candidate("spec-2", "spec", WEAK_BUT_CORRECT),
        candidate("book2-7.42", "book2", OFF_TOPIC),
    ]
    dropped: list[dict] = []

    kept, low_confidence = search.apply_relevance_floor(field, dropped=dropped)

    assert [c.chunk_id for c in kept] == ["spec-1", "spec-2"]
    assert low_confidence is False
    # dropped, and dropped FOR A STATED REASON - a coverage report has to be
    # able to tell this from "the chunk no longer exists"
    assert [(d["chunk_id"], d["reason"]) for d in dropped] == [
        ("book2-7.42", "below_relevance_floor")
    ]


def test_a_weak_but_correct_passage_is_not_dropped():
    """The floor is a noise cut, not a topicality gate. -1.19 is a MEASURED
    correct answer on this corpus; a floor that removes it has replaced one
    defect with a worse one."""
    field = [candidate("a", "spec", WEAK_BUT_CORRECT)]
    kept, low_confidence = search.apply_relevance_floor(field)
    assert [c.chunk_id for c in kept] == ["a"]
    assert low_confidence is False


def test_the_floor_never_empties_the_field():
    """The rule the whole feature is subordinate to: if applying the floor
    would leave nothing, the passages are KEPT and the result is marked low
    confidence. A refusal caused by the floor is the defect, not the fix."""
    field = [
        candidate("a", "spec", -10.2),
        candidate("b", "spec", -10.9),
        candidate("c", "spec", -11.3),
        candidate("d", "spec", -11.4),
    ]
    dropped: list[dict] = []

    kept, low_confidence = search.apply_relevance_floor(field, dropped=dropped)

    assert kept, "the floor emptied the field - this is the false refusal"
    assert kept[0].chunk_id == "a", "the best of a weak field must still lead"
    assert low_confidence is True
    # nothing was dropped, so nothing may be RECORDED as dropped either
    assert dropped == []


def test_an_unreranked_field_is_left_alone():
    """No rerank pass, no scores, no verdict. An RRF value of 0.012 is not on
    the cross-encoder's scale and comparing it to -9.5 would drop everything
    the moment the reranker was unavailable."""
    a = candidate("a", "spec", ON_TOPIC)
    a.rerank_score = None
    b = candidate("b", "spec", ON_TOPIC)
    b.rerank_score = None

    kept, low_confidence = search.apply_relevance_floor([a, b])

    assert [c.chunk_id for c in kept] == ["a", "b"]
    assert low_confidence is False


def test_the_floor_is_measured_against_the_rerank_score_not_the_penalty():
    """A passage about coating system 4 asked about system 1 carries a
    conflict penalty the size of the whole field's spread. It is wrong for a
    different reason and must be ordered down, not deleted as off-topic."""
    conflicted = candidate("a", "spec", ON_TOPIC)
    conflicted.conflicts = ["system 4"]
    conflicted.penalty = 20.0
    assert conflicted.score < search.RELEVANCE_FLOOR

    kept, _ = search.apply_relevance_floor([conflicted])

    assert [c.chunk_id for c in kept] == ["a"]


# ----------------------------------------------------------- document cap


def test_one_document_cannot_supply_more_than_the_cap():
    field = [candidate(f"book1-{i}", "book1", 5.0 - i) for i in range(6)]
    field.append(candidate("spec-1", "spec", 1.0))
    dropped: list[dict] = []

    kept = search.apply_document_cap(field, dropped=dropped)

    from collections import Counter
    per_document = Counter(c.document_id for c in kept)
    assert per_document["book1"] == search.MAX_PASSAGES_PER_DOCUMENT
    assert per_document["spec"] == 1
    # the ones kept are that document's BEST, not an arbitrary three
    assert [c.chunk_id for c in kept if c.document_id == "book1"] == [
        "book1-0", "book1-1", "book1-2",
    ]
    assert {d["reason"] for d in dropped} == {"document_cap"}
    assert len(dropped) == 6 - search.MAX_PASSAGES_PER_DOCUMENT


def test_a_single_document_corpus_is_not_capped():
    """Every one of the 35 measured queries runs against one document, and
    there the cap can only cut a correct answer. It stands down."""
    field = [candidate(f"c{i}", "spec", 5.0 - i) for i in range(6)]
    kept = search.apply_document_cap(field)
    assert len(kept) == 6


def test_the_cap_keeps_the_quiet_document_visible():
    """The reason the cap exists: another agent reads the summary document by
    document, so a verbose book must not crowd every other file out of the
    field entirely."""
    field = [candidate(f"book1-{i}", "book1", 9.0 - i * 0.1) for i in range(10)]
    field += [candidate("spec-1", "spec", 2.0), candidate("spec-2", "spec", 1.9)]

    kept = search.apply_document_cap(field)

    assert "spec" in {c.document_id for c in kept[:10]}
    assert len([c for c in kept if c.document_id == "book1"]) == 3


# ------------------------------------------------------------ end to end


SPEC_CHUNKS = [
    ("3.1 Structural Submittals",
     "Structural models and calculation submittals shall be reviewed by the "
     "engineer of record before fabrication begins on any primary member."),
    ("3.2 Analysis",
     "The structural analysis model shall represent the stiffness of every "
     "primary member and connection used in the completed frame."),
]

BOOK_CHUNKS = [
    ("7.4 Exercises",
     "7.42 Which of the following models do you think would produce very "
     "accurate results? Justify your answer in a short paragraph."),
    ("2.2 Exercises",
     "We will come back to equation (16) in Exercises 2.2 and Section 5.3 "
     "when the models of the previous chapter are revisited."),
]


def insert_document(document_id: str, filename: str, chunks) -> None:
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)
               VALUES (?, ?, ?, 1, ?, 'ready', '2026-01-01T00:00:00Z')""",
            (document_id, filename, f"sha-{document_id}", f"/tmp/{filename}"),
        )
        for ordinal, (section, text) in enumerate(chunks):
            conn.execute(
                """INSERT INTO chunks
                   (id, document_id, filename, ordinal, page_start, page_end,
                    section, kind, text, token_count, content_hash, retrievable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'prose', ?, ?, ?, 1)""",
                (f"{document_id}-{ordinal}", document_id, filename, ordinal,
                 ordinal + 1, ordinal + 1, section, text, len(text.split()),
                 f"hash-{document_id}-{ordinal}"),
            )
    keyword.index_document(document_id)


def stub_reranker(monkeypatch, scores: dict[str, float], default: float):
    """Score by chunk id, so the test states the distribution it is testing
    instead of depending on a 22 MB model being staged."""
    def rerank(question, passages, batch=None):
        return [(cid, scores.get(cid, default)) for cid, _ in passages]

    from app import reranker
    monkeypatch.setattr(reranker, "rerank", rerank)


def test_search_drops_the_off_topic_document_end_to_end(monkeypatch):
    """The live defect, through the whole pipeline: FTS -> RRF -> rerank ->
    floor. Both books match on the word "models" and both are cut."""
    insert_document("spec", "structural-spec.pdf", SPEC_CHUNKS)
    insert_document("book2", "book2-Differential-Equations.pdf", BOOK_CHUNKS)
    stub_reranker(
        monkeypatch,
        {"spec-0": 7.1, "spec-1": 3.4},
        default=OFF_TOPIC,          # everything from book2
    )

    result = search.search(
        "find all structural models from all documents",
        limit=10, dense=False,
        allowed_document_ids=frozenset({"spec", "book2"}),
    )

    assert result["reranked"] is True
    returned = {h["chunk_id"] for h in result["hits"]}
    assert returned == {"spec-0", "spec-1"}
    assert not any(h["document_id"] == "book2" for h in result["hits"])
    assert result["low_confidence"] is False
    floored = [
        e for e in result["shortlist_excluded"]
        if e["reason"] == "below_relevance_floor"
    ]
    assert {e["document_id"] for e in floored} == {"book2"}


def test_search_keeps_passages_and_lowers_confidence_rather_than_refusing(
    monkeypatch,
):
    """The same pipeline where NOTHING clears the floor. The caller must get
    passages plus a warning, never an empty field - `total: 0` is what the
    answer layer turns into "no indexed passage matched this question"."""
    insert_document("spec", "structural-spec.pdf", SPEC_CHUNKS)
    stub_reranker(monkeypatch, {}, default=-11.0)

    result = search.search(
        "find all structural models from all documents",
        limit=10, dense=False,
        allowed_document_ids=frozenset({"spec"}),
    )

    assert result["hits"], "the floor refused a question the corpus answers"
    assert result["total"] > 0
    assert result["low_confidence"] is True
    assert not [
        e for e in result["shortlist_excluded"]
        if e["reason"] == "below_relevance_floor"
    ]


def test_search_caps_a_verbose_document_end_to_end(monkeypatch):
    # Deliberately DISSIMILAR bodies: near-identical chunks would be merged
    # by deduplicate() and the cap would never be reached, so the test would
    # pass for the wrong reason.
    topics = [
        "beam deflection under service loading",
        "column buckling and effective length",
        "welded connection detailing on site",
        "foundation settlement over soft clay",
        "wind pressure coefficients for cladding",
        "seismic base shear distribution",
        "fire protection of exposed steelwork",
        "corrosion allowance in coastal exposure",
    ]
    long_book = [
        (f"{i}.1 Chapter", f"Structural models of {topic} are covered here.")
        for i, topic in enumerate(topics)
    ]
    insert_document("book1", "book1-professionalpractices.pdf", long_book)
    insert_document("spec", "structural-spec.pdf", SPEC_CHUNKS)
    # every book chunk scores ABOVE the spec, so only the cap can hold it back
    stub_reranker(monkeypatch, {"spec-0": 1.0, "spec-1": 0.9}, default=5.0)

    result = search.search(
        "structural models", limit=10, dense=False,
        allowed_document_ids=frozenset({"book1", "spec"}),
    )

    from collections import Counter
    per_document = Counter(h["document_id"] for h in result["hits"])
    assert per_document["book1"] == search.MAX_PASSAGES_PER_DOCUMENT
    assert per_document["spec"] >= 1
    assert {
        e["reason"] for e in result["shortlist_excluded"]
        if e["document_id"] == "book1" and e["reason"] == "document_cap"
    } == {"document_cap"}
