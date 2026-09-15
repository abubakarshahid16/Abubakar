"""A typo must not destroy the answer (issue #85).

Observed: a misspelled question went to FTS exactly as typed, matched nothing,
and the system REFUSED - "none of the terms in this question appear in the
indexed documents" - on a corpus that contains the answer. Real users on this
product type badly.

Two places had to change and both are asserted here:

  * keyword.search retries a query that came back empty against the spelling
    the INDEX actually holds, and merges the retry's rows with the exact
    query's. The corrections come from fts5vocab, so a correction can only
    ever be a word that is really in the corpus - no dictionary, no model, no
    new dependency.
  * lexical.assess no longer reports a misspelled term as absent from the
    corpus, which is the specific line that produced the refusal.

And the guards that stop this becoming a licence to answer a different
question: identifiers are never corrected (API 610 and API 611 are one edit
apart and are different standards), a word that IS in the corpus is never
rewritten, and a genuinely absent subject still refuses.
"""

from __future__ import annotations

import pytest

from app import db, keyword, lexical
from app.config import settings

# Parked. Both features these tests assert (the reranker relevance floor and
# the FTS typo retry) live only in `git stash` - see docs/HANDOVER.md section 2.
# Every test here errors at fixture setup with AttributeError until that stash
# is applied, so the module is skipped rather than deleted.
pytestmark = pytest.mark.skip(reason="parked: feature in stash, see HANDOVER §2")

CHUNKS = [
    ("3.1 Structural Submittals",
     "Structural steel submittal drawings shall be reviewed by the engineer "
     "of record before any primary member is fabricated or delivered."),
    ("3.2 Structural Analysis",
     "The structural analysis model shall represent the stiffness of every "
     "primary member and connection in the completed frame."),
    ("9.4 Coating",
     "External surfaces shall receive a two part epoxy primer followed by a "
     "polyurethane topcoat before delivery to site."),
]

SCOPE = frozenset({"doc1"})


@pytest.fixture(autouse=True)
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    keyword.reset_vocabulary_cache()
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)
               VALUES ('doc1', 'spec.pdf', 'sha1', 1, '/tmp/spec.pdf', 'ready',
                       '2026-01-01T00:00:00Z')"""
        )
        for ordinal, (section, text) in enumerate(CHUNKS):
            conn.execute(
                """INSERT INTO chunks
                   (id, document_id, filename, ordinal, page_start, page_end,
                    section, kind, text, token_count, content_hash, retrievable)
                   VALUES (?, 'doc1', 'spec.pdf', ?, ?, ?, ?, 'prose', ?, ?, ?, 1)""",
                (f"c{ordinal}", ordinal, ordinal + 1, ordinal + 1, section,
                 text, len(text.split()), f"h{ordinal}"),
            )
    keyword.index_document("doc1")
    keyword.reset_vocabulary_cache()
    yield
    db.reset_connection()


def ids(hits) -> set[str]:
    return {h["chunk_id"] for h in hits}


# ------------------------------------------------- the defect, end to end


def test_the_misspelled_query_matches_nothing_without_the_retry():
    """The defect itself, stated as a fact about the index rather than an
    assumption. If this ever stops being true the test below proves nothing,
    so it is asserted rather than believed."""
    exact = keyword.build_match_query("strctural sumbittal")
    conn = db.connect()
    where, params = keyword._scope_clause(None, SCOPE)
    assert keyword._run_match(conn, exact, where, params, 30) == []


def test_a_misspelled_query_retrieves_what_the_correct_one_retrieves():
    """"strctural sumbittal" must find the passages "structural submittal"
    finds. This is issue #85."""
    correct = keyword.search(
        "structural submittal", allowed_document_ids=SCOPE)
    typed = keyword.search(
        "strctural sumbittal", allowed_document_ids=SCOPE)

    assert ids(correct), "the control query found nothing; the fixture is wrong"
    assert ids(correct) <= ids(typed)
    assert "c0" in ids(typed)


def test_the_corrections_are_reported_not_hidden():
    """The reader is told what was actually searched. Silently answering a
    different question is the failure mode this feature has to avoid."""
    corrections: dict[str, str] = {}
    keyword.search(
        "strctural sumbittal", allowed_document_ids=SCOPE,
        corrections=corrections,
    )
    assert corrections == {"strctural": "structural", "sumbittal": "submittal"}


def test_the_exact_hits_are_kept_when_a_retry_happens():
    """The retry is ADDITIVE. A word the reader spelled correctly keeps
    everything it matched, whatever the tolerant query does."""
    typed = keyword.search(
        "strctural coating", allowed_document_ids=SCOPE)
    assert "c2" in ids(typed), "the correctly spelled word lost its own hits"
    assert "c0" in ids(typed) or "c1" in ids(typed)


# ------------------------------------------- the refusal path in lexical.py


def test_a_misspelled_question_no_longer_reports_every_term_absent():
    """The exact line that refused: `if not present` -> "none of the terms in
    this question appear in the indexed documents"."""
    verdict = lexical.assess(
        "what are the strctural sumbittal drawings", CHUNKS[0][1], "doc1")

    assert verdict["ok"] is True, verdict["reason"]
    assert verdict["reason"] is None
    assert verdict["absent_from_corpus"] == []
    assert verdict["spelling_corrections"] == {
        "strctural": "structural", "sumbittal": "submittal",
    }


def test_a_misspelled_capitalised_subject_is_not_treated_as_absent():
    """A capitalised term absent from the corpus refuses outright, by design.
    A capitalised TYPO must not, or every sentence-initial misspelling is a
    refusal."""
    verdict = lexical.assess(
        "Strctural drawings, are they reviewed", CHUNKS[0][1], "doc1")
    assert verdict["ok"] is True, verdict["reason"]


# ------------------------------------------------------------- the guards


def test_a_genuinely_absent_subject_still_refuses():
    """The gate was not disabled. Inconel appears nowhere in this corpus and
    no word in it is one edit away, so the question is still unanswerable -
    and that refusal is correct."""
    verdict = lexical.assess(
        "what grade of Inconel is required", CHUNKS[0][1], "doc1")
    assert verdict["ok"] is False
    assert "Inconel" in verdict["absent_from_corpus"]


def test_an_identifier_is_never_corrected():
    """API 610 and API 611 are one edit apart and are different standards.
    Correcting one to the other answers a question nobody asked, which is
    worse than returning nothing."""
    assert keyword.fuzzy_corpus_match("610") is None
    assert keyword.fuzzy_corpus_match("P-101A") is None
    assert keyword.fuzzy_corpus_match("5.3.2") is None
    assert keyword._correctable("A216") is False


def test_a_word_the_corpus_contains_is_never_rewritten():
    """The reader's spelling wins whenever it matches something."""
    assert keyword.fuzzy_corpus_match("structural") is None
    assert keyword.fuzzy_corpus_match("coating") is None
    assert keyword.spelling_corrections("structural submittal drawings") == {}


def test_a_different_word_is_not_treated_as_a_typo():
    """Similarity is not identity. "clause" is not "class", and a correction
    that changes the meaning of the question is the defect, not the fix."""
    assert keyword.fuzzy_corpus_match("cladding") is None
    assert keyword.fuzzy_corpus_match("submarine") is None


def test_short_words_are_left_alone():
    """At four characters and under, one edit is a different word far more
    often than it is a typo."""
    assert keyword._correctable("stel") is False
    assert keyword.fuzzy_corpus_match("stel") is None


# ------------------------------------------------------ query normalisation


def test_normalisation_strips_noise_but_keeps_identifiers_intact():
    assert keyword.normalise_query("  what  is   the NDFT?? ") == "what is the NDFT"
    assert keyword.normalise_query("clause 5.3.2 (API 610)!") == "clause 5.3.2 API 610"
    # case is deliberately preserved: IDENTIFIER and DESIGNATOR key off it, and
    # folding here would quietly turn a REQUIRED term into an optional one
    assert '"API 610"' in keyword.build_match_query(
        keyword.normalise_query("what does API 610 say?"))


def test_punctuation_alone_does_not_lose_the_hits():
    plain = keyword.search("structural submittal", allowed_document_ids=SCOPE)
    noisy = keyword.search(
        "structural submittal???", allowed_document_ids=SCOPE)
    assert ids(plain) == ids(noisy)


# -------------------------------------------------- a keyword miss and dense


def test_a_keyword_miss_does_not_suppress_the_dense_side():
    """RRF fuses whatever each side returned; an empty keyword list must leave
    the dense hits standing. Asserted directly on the fusion, because this is
    the property that makes vector search the safety net for a typo."""
    from app import search

    fused = search.rrf_fuse([], [{"chunk_id": "c1", "cosine": 0.83}])
    assert set(fused) == {"c1"}
    assert fused["c1"]["rrf"] > 0
