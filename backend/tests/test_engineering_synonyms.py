"""Engineering synonyms (app/glossary.py): the typed word reaches the page that
prints the document's word for it - keyword side only, additive, reported.

The two measured misses of docs/limitations.md, rebuilt on synthetic pages:
"how humid" vs "relative humidity", "salt" vs "chlorides"/"NaCl".
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import glossary, keyword, search
from app.main import app
from tests.test_correctness_fixes import AMBIENT, INSPECTION, temp_storage, upload  # noqa: F401

SOLUBLE = [
    "6.3",
    "Soluble impurities",
    "The level of chlorides on the blast cleaned surface shall not exceed",
    "20 mg/m2 measured as NaCl before any coating is applied to the steel.",
]
FILLER = [
    "2.1",
    "Normative references",
    "The following documents are referred to in the text in such a way that",
    "some or all of their content constitutes requirements of this document.",
]


@pytest.fixture
def corpus():
    upload(TestClient(app), [FILLER, AMBIENT, SOLUBLE, INSPECTION])
    return search.every_document_id()


def _clauses(hits):
    return {(h["section"] or "").split(" ")[0] for h in hits}


def test_a_lay_word_reaches_the_page_that_prints_the_documents_word(corpus):
    for question, clause in (("how humid is too humid to paint", "4.4"),
                             ("how much salt is allowed on the surface", "6.3")):
        hits = keyword.search(question, allowed_document_ids=corpus)
        assert clause in _clauses(hits), question


def test_without_the_glossary_those_pages_were_not_reached(corpus, monkeypatch):
    """The miss is real on this corpus, so the test above proves the glossary
    and not something else."""
    monkeypatch.setattr(glossary, "GLOSSARY", {})
    assert "4.4" not in _clauses(keyword.search("how humid is too humid",
                                                allowed_document_ids=corpus))
    assert "6.3" not in _clauses(keyword.search("how much salt is allowed",
                                                allowed_document_ids=corpus))


def test_the_expansion_is_reported_never_silent(corpus):
    result = search.search("how much salt is allowed on the surface",
                           allowed_document_ids=corpus, rerank=False, dense=False)
    assert "chlorides" in result["synonyms_searched"]["salt"]


def test_the_typed_word_is_kept_not_replaced(corpus):
    synonyms: dict = {}
    keyword.search("salt", allowed_document_ids=corpus, synonyms=synonyms)
    assert synonyms == {"salt": list(glossary.GLOSSARY["salt"][0])}
    variants = keyword._glossary_variants("salt spray")
    assert "salt spray" not in variants and "spray" not in variants


def test_a_word_with_no_entry_is_untouched(corpus):
    synonyms: dict = {}
    keyword.search("design pressure", allowed_document_ids=corpus, synonyms=synonyms)
    assert synonyms == {}


def test_every_entry_says_why_and_maps_lay_to_technical_only():
    for word, (phrases, why) in glossary.GLOSSARY.items():
        assert word == word.lower() and phrases and why.strip(), word
        assert word not in phrases, f"{word} lists itself"


# ------------------------------------------------ end to end, with the reranker

from app import answer as answer_mod  # noqa: E402


@pytest.mark.parametrize("question,clause", [
    ("how humid is too humid to paint", "4.4"),
    ("how much salt is allowed on the surface", "6.3"),
])
def test_the_two_measured_misses_now_answer_from_the_right_clause(corpus, question, clause):
    result = answer_mod.answer(question, allowed_document_ids=corpus)
    assert result["answer_type"] == "extract", result.get("reason")
    assert (result["passage"]["section"] or "").startswith(clause)


@pytest.mark.parametrize("question", [
    "what salt spray test duration is required",       # a different term: never widened
    "what paint colour is required for the handrails",  # expanded, still absent
    "what is the warranty period",
])
def test_an_absent_answer_still_refuses(corpus, question):
    assert answer_mod.answer(question, allowed_document_ids=corpus)["answer_type"] \
        == "insufficient_evidence"


def test_salt_spray_is_never_widened_to_chlorides():
    assert glossary.expansions("salt spray test hours") == {}
    assert glossary.rewrite("salt spray test hours") is None
    assert glossary.rewrite("How much SALT, and any salt spray?") == "How much chlorides, and any salt spray?"


def test_each_passage_keeps_the_higher_of_the_two_scores(corpus, monkeypatch):
    """The rewrite may only ADD a chance: a passage that fits the reader's own
    wording better keeps that score."""
    from app import reranker

    def fake(question, passages, batch=None):
        own = "paint" in question
        return [(cid, 5.0 if own else -9.0) for cid, _ in passages]

    monkeypatch.setattr(reranker, "rerank", fake)
    result = search.search("how humid is too humid to paint", allowed_document_ids=corpus,
                           dense=False)
    scores = [r["rerank_score"] for r in result["hits"] if r.get("rerank_score") is not None]
    assert scores and min(scores) >= 5.0
