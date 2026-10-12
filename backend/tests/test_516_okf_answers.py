"""#516 (R29 #833): no uncited answer from the graph.

An answer made from the reference graph is a list of sentences, each with
what it rests on. A sentence is released only when it names at least one
thing and EVERY thing it names resolves: a concept that is in the graph and
ok, an edge that is in the graph, or a raw citation that resolves. One bad
citation refuses the whole sentence, and a refused sentence's text is not
returned.

Invented standard only; no model, no socket.
"""
from __future__ import annotations

import pytest

from app import db, okf
from tests.test_513_okf import NOISE, _build, library  # noqa: F401 - autouse fixture


@pytest.fixture
def world():
    concepts = _build()["concepts"]
    return concepts, okf.graph(concepts)


def _ids(concepts):
    by_kind = {}
    for concept in concepts:
        by_kind.setdefault(concept["kind"], []).append(concept["id"])
    return by_kind


def _check(sentences, world):
    concepts, built = world
    return okf.check_answer(sentences, built, concepts)


def test_a_sentence_resting_on_a_requirement_a_clause_and_an_edge_is_kept(world):
    concepts, built = world
    ids = _ids(concepts)
    edge = built["edges"][0]
    out = _check([
        {"text": "Clause 5.3.3 limits the noise level.", "cites": [{"concept": ids["requirement"][0]}]},
        {"text": "It is a clause of this standard.", "cites": [{"concept": ids["clause"][0]},
                                                               {"edge": {k: edge[k] for k in ("from", "rel", "to")}}]},
        {"text": "The limit is stated on page 1.", "cites": [
            {"cite": {"document_id": "doc_std", "page": 1, "chunk_id": "c1", "quote": NOISE}}]},
        {"text": "This standard has two clauses with requirements.", "cites": [{"concept": ids["standard"][0]}]},
    ], world)
    assert len(out["kept"]) == 4 and out["refused"] == [] and out["counts"] == {}


@pytest.mark.parametrize("sentence, reason", [
    ({"text": "Pumps are generally noisy.", "cites": []}, okf.UNCITED),                       # the summary that cites nothing
    ({"text": "Pumps are generally noisy."}, okf.UNCITED),
    ({"text": "", "cites": [{"concept": "okf:standard:doc_std"}]}, okf.UNCITED),
    ({"text": "A clause nobody stored.", "cites": [{"concept": "okf:clause:doc_std:9.9"}]}, okf.CONCEPT_MISSING),
    ({"text": "A made-up relation.", "cites": [{"edge": {"from": "okf:clause:doc_std:5.3.3", "rel": "part_of",
                                                         "to": "okf:standard:doc_other"}}]}, okf.EDGE_MISSING),
    ({"text": "The limit is 95.", "cites": [{"cite": {"document_id": "doc_std", "page": 1, "chunk_id": "c1",
                                                      "quote": "shall not exceed 95"}}]}, okf.QUOTE_ABSENT),
    ({"text": "Cites another document's chunk.", "cites": [{"cite": {"document_id": "doc_std", "page": 1,
                                                                       "chunk_id": "cx"}}]}, okf.WRONG_DOCUMENT),
    ({"text": "Cites a word.", "cites": ["page 12"]}, okf.BAD_REFERENCE),
    ({"text": "Cites an empty thing.", "cites": [{}]}, okf.BAD_REFERENCE),
])
def test_a_sentence_that_is_not_fully_cited_is_refused_with_a_named_reason(world, sentence, reason):
    out = _check([sentence], world)
    assert out["kept"] == [] and out["refused"] == [{"index": 0, "reason": reason}] and out["counts"] == {reason: 1}


def test_one_bad_citation_refuses_the_whole_sentence(world):
    """A half-supported sentence is not shown with its good half."""
    concepts, _built = world
    good = {"concept": _ids(concepts)["requirement"][0]}
    out = _check([{"text": "Noise is limited and vibration is unlimited.",
                   "cites": [good, {"concept": "okf:clause:doc_std:9.9"}]}], world)
    assert out["kept"] == [] and out["counts"] == {okf.CONCEPT_MISSING: 1}


def test_a_concept_whose_own_source_no_longer_resolves_supports_nothing(world):
    concepts, built = world
    requirement = next(c for c in concepts if c["kind"] == "requirement" and c["source"]["chunk_id"] == "c2")
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE id = 'c2'")
    out = okf.check_answer([{"text": "Vibration is limited.", "cites": [{"concept": requirement["id"]}]}],
                           built, concepts)
    assert out["kept"] == [] and out["counts"] == {okf.CHUNK_MISSING: 1}


def test_a_concept_that_is_not_ok_supports_nothing():
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET text = 'The page was re-read and says something else.' WHERE id = 'c2'")
    concepts = _build()["concepts"]
    bad = next(c for c in concepts if c["state"] != okf.OK)
    out = okf.check_answer([{"text": "Vibration is limited.", "cites": [{"concept": bad["id"]}]}],
                           okf.graph(concepts), concepts)
    assert out["counts"] == {okf.CONCEPT_NOT_OK: 1}


def test_a_standard_no_cited_edge_reaches_supports_nothing():
    """A standard has no page of its own: it holds through an edge."""
    concepts = [c for c in _build()["concepts"] if c["kind"] == "standard"]
    out = okf.check_answer([{"text": "This standard covers pumps.", "cites": [{"concept": concepts[0]["id"]}]}],
                           okf.graph(concepts), concepts)
    assert out["kept"] == [] and out["counts"] == {okf.UNCITED: 1}


def test_good_sentences_are_kept_in_order_and_a_refused_ones_text_is_not_returned(world):
    concepts, _built = world
    good = {"concept": _ids(concepts)["requirement"][0]}
    out = _check([{"text": "First, cited.", "cites": [good]},
                  {"text": "SECOND-AND-UNCITED", "cites": []},
                  {"text": "Third, cited.", "cites": [good]}], world)
    assert [s["text"] for s in out["kept"]] == ["First, cited.", "Third, cited."]
    assert out["refused"] == [{"index": 1, "reason": okf.UNCITED}]
    assert "SECOND-AND-UNCITED" not in str(out)


def test_an_empty_or_odd_answer_releases_nothing(world):
    assert _check([], world) == {"kept": [], "refused": [], "counts": {}}
    assert _check(None, world) == {"kept": [], "refused": [], "counts": {}}
    out = _check(["just a string", 7], world)
    assert out["kept"] == [] and out["counts"] == {okf.UNCITED: 2}
