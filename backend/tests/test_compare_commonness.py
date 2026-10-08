"""A standard that covers the topic in many places must not be reported silent
on it (found 2026-10-02 on the owner's library).

`chat_comparison` searches each standard on its own. The lexical gate judges a
word "common" when it sits in more than a quarter of the chunks it is looking
at, and a common word no longer counts as a distinctive term. Looking only at
ONE standard, a standard that discusses post weld heat treatment in a good
share of its own pages made those words "common to the whole document", so the
side was refused with "the closest passage shares only 1 of the 2 distinctive
terms" and shown as "Not found in the pages read" - the more it covered the
topic, the likelier it was called silent.

Synthetic standards only (STD-K-117 is invented).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat_comparison, keyword, lexical
from app.main import app
from tests.test_chat_comparison import temp_storage, upload  # noqa: F401

QUESTION = "What does STD-K-117 say about post weld heat treatment?"


def _pwht_page(n: int) -> list[str]:
    return [
        f"{n}.1 Post Weld Heat Treatment",
        f"Post weld heat treatment of weld joint type {n} shall be carried out",
        "by the contractor under a written procedure approved before work starts,",
        f"with the heat treatment record for joint {n} kept for the owner.",
    ]


def _plain_page(n: int, word: str) -> list[str]:
    return [
        f"{n}.1 {word.title()} Requirements",
        f"The {word} for item {n} shall be installed as shown on the drawing,",
        "inspected by the site engineer and recorded in the daily log together",
        "with the batch number supplied by the manufacturer of the item.",
    ]


@pytest.fixture()
def library(temp_storage):  # noqa: F811
    client = TestClient(app)
    # One standard that talks about the topic on 10 of its 24 pages ...
    pages = [_pwht_page(i) for i in range(10)] + [_plain_page(i, "gasket") for i in range(14)]
    target = upload(client, pages, "STD-K-117.pdf")
    # ... in a library where the topic is rare.
    others = []
    for k, word in enumerate(("bolting", "painting", "valve", "pump")):
        others.append(upload(client, [_plain_page(i, word) for i in range(22)], f"STD-X-10{k}.pdf"))
    return target, frozenset({target, *others})


def test_the_library_is_big_enough_to_judge_commonness(library):
    target, everything = library
    assert keyword.indexed_count(None, allowed_document_ids=frozenset({target})) >= lexical.MIN_CORPUS_FOR_COMMONNESS
    inside = keyword.term_occurrences("treatment", None, allowed_document_ids=frozenset({target}))
    across = keyword.term_occurrences("treatment", None, allowed_document_ids=everything)
    assert inside == across  # the topic lives only in the standard that covers it
    assert inside > int(keyword.indexed_count(None, allowed_document_ids=frozenset({target})) * lexical.COMMON_TERM_FRACTION)
    assert across <= int(keyword.indexed_count(None, allowed_document_ids=everything) * lexical.COMMON_TERM_FRACTION)


def test_a_standard_that_covers_the_topic_is_not_refused_as_common(library):
    """THE MUTATION TARGET: with commonness judged across what the caller may
    read, the standard that covers the topic answers."""
    target, everything = library
    with lexical.commonness_against(everything):
        result = answer_mod.answer(QUESTION, tier="extract", document_id=None,
                                   allowed_document_ids=frozenset({target}))
    assert result["answer_type"] != "insufficient_evidence", result.get("reason")


def test_judged_inside_the_one_standard_it_is_still_refused(library):
    """The behaviour the fix is for. If this ever passes without the context,
    the first test no longer proves anything."""
    target, _ = library
    result = answer_mod.answer(QUESTION, tier="extract", document_id=None,
                               allowed_document_ids=frozenset({target}))
    assert result["answer_type"] == "insufficient_evidence"
    assert "distinctive" in (result.get("reason") or "") or "common" in (result.get("reason") or "")


def test_compare_gives_the_covering_standard_its_answer(library):
    target, everything = library
    out = chat_comparison.compare(
        "what do the welding standards say about post weld heat treatment",
        [("STD-K-117", frozenset({target}))], tier="extract",
        allowed_document_ids=everything, progress_id=None, model=None, history="",
        topic="post weld heat treatment")
    side = out["comparison"]["sides"][0]
    assert side["answer_type"] != "insufficient_evidence"
    assert "Not found" not in (side["text"] or "")
