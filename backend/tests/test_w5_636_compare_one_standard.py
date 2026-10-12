"""#636: "Compare ASME B16.5 and ASME B16.47: which flange size range does each
standard cover?" produced THREE sides, "ASME-B16.5" (not found in the pages
read), "B16.5" and "B16.47" (not among the documents you can read), although
both standards were in the library.

The fix groups by the standard's IDENTITY (the shared matcher, `standard_ids`),
never by document title; and every side is searched for the question's TOPIC.
Synthetic names and text only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_comparison, standard_ids
from app.main import app
from tests.test_chat_comparison import PWHT_TEMPERATURE, temp_storage, upload  # noqa: F401

QUESTION = ("Compare ASME B16.5 and ASME B16.47: which flange size range does each "
            "standard cover?")


def _sides(documents: dict[str, str], question: str = QUESTION):
    sides, missing = chat_comparison.resolve_sides(question, documents)
    return {name: sorted(ids) for name, ids in sides}, missing


# ------------------------------------------------- one standard is one side

@pytest.mark.parametrize("documents", [
    {"a": "ASME B16.5-2020.pdf", "b": "ASME B16.47-2020.pdf"},
    {"a": "ASME-B16.5.pdf", "b": "ASME-B16.47.pdf"},
    {"a": "B16.5.pdf", "b": "B16.47.pdf"},
    {"a": "asme_b16_5.pdf", "b": "asme_b16_47.pdf"},
])
def test_the_live_question_gives_two_sides_whatever_the_files_are_called(documents):
    sides, missing = _sides(documents)
    assert missing == []
    assert len(sides) == 2, sides
    assert sorted(sum(sides.values(), [])) == ["a", "b"]
    assert {tuple(v) for v in sides.values()} == {("a",), ("b",)}


def test_one_standard_filed_as_three_documents_is_one_side():
    documents = {"a": "ASME B16.5-2020.pdf", "b": "ASME B16.5 Annex A.pdf",
                 "c": "ASME-B16.5 errata.pdf", "d": "ASME B16.47-2020.pdf"}
    sides, missing = _sides(documents)
    assert missing == []
    assert len(sides) == 2
    assert sorted(max(sides.values(), key=len)) == ["a", "b", "c"]


def test_the_standard_typed_two_ways_is_one_side_and_not_missing():
    sides, missing = _sides({"a": "ASME-B16.5.pdf", "b": "ASME-B16.47.pdf"},
                            "compare ASME B16.5 and B16.5 on flange sizes with ASME B16.47")
    assert missing == [] and len(sides) == 2


def test_a_typed_standard_the_library_does_not_hold_is_missing_once():
    sides, missing = _sides({"a": "ASME B16.5-2020.pdf"})
    assert list(sides.values()) == [["a"]]
    assert missing == ["ASME B16.47"]
    # A different standard with the same leading digits is not the held one.
    sides, missing = _sides({"a": "ASME B16.5.pdf"}, "compare ASME B16.5 and ASME B16.50 on sizes")
    assert list(sides.values()) == [["a"]] and missing == ["ASME B16.50"]


# ----------------------------------------------- two editions are two sides

def test_two_editions_of_one_standard_are_two_sides_each_labelled_with_its_edition():
    documents = {"a": "ASME B16.5-2013.pdf", "b": "ASME B16.5-2020.pdf",
                 "c": "ASME B16.47-2020.pdf", "d": "ASME B16.5-2020 addendum.pdf"}
    sides, missing = _sides(documents)
    assert missing == []
    assert sides == {"ASME B16.47": ["c"], "ASME B16.5 (2013)": ["a"],
                     "ASME B16.5 (2020)": ["b", "d"]}


def test_a_copy_with_no_edition_is_not_merged_into_a_named_edition():
    sides, _ = _sides({"a": "ASME B16.5-2013.pdf", "b": "ASME B16.5.pdf",
                       "c": "ASME B16.5-2020.pdf", "d": "ASME B16.47.pdf"})
    assert sides["ASME B16.5 (edition not stated)"] == ["b"]
    assert sides["ASME B16.5 (2013)"] == ["a"] and sides["ASME B16.5 (2020)"] == ["c"]


def test_the_edition_is_a_printed_year_never_part_of_the_number():
    assert standard_ids.edition_of("ASME B16.5-2020.pdf") == "2020"
    assert standard_ids.edition_of("ASME B16.47.pdf") is None
    assert standard_ids.edition_of("API 12345.pdf") is None
    assert standard_ids.edition_of("API 650 2013 replaces 1998.pdf") == "1998"
    assert standard_ids.edition_of("API 650 (2020).pdf") == "2020"


def test_sides_are_grouped_by_identity_not_by_title(monkeypatch):
    """Titles that differ entirely, one standard: the identifier decides."""
    documents = {"a": "ASME B16.5 Pipe Flanges and Flanged Fittings NPS 1/2 through NPS 24.pdf",
                 "b": "ASME B16.5 - metric.pdf", "c": "ASME B16.47 Large Diameter Steel Flanges.pdf"}
    sides, _ = _sides(documents)
    assert len(sides) == 2 and sorted(max(sides.values(), key=len)) == ["a", "b"]


# ---------------------------------------------- a side is searched for the topic

def test_the_topic_has_no_standard_name_left_in_it():
    assert chat_comparison.topic_of(QUESTION, []) == "which flange size range does each standard cover"
    assert chat_comparison.topic_of(QUESTION, ["ASME-B16.5", "B16.47"]) == \
        "which flange size range does each standard cover"


def test_every_side_is_asked_about_the_topic_and_only_its_own_standard(monkeypatch):
    asked = []

    def fake(side_question, ids, **_kw):
        asked.append((side_question, sorted(ids)))
        return {"answer_type": "insufficient_evidence", "answer": None, "passages": [],
                "candidates_considered": 0, "reranked": False, "seconds": 0.0}

    monkeypatch.setattr(chat_comparison, "_side_answer", fake)
    documents = {"a": "ASME-B16.5.pdf", "b": "ASME-B16.47.pdf"}
    sides, missing = chat_comparison.resolve_sides(QUESTION, documents)
    chat_comparison.compare(QUESTION, sides, tier="generated",
                            allowed_document_ids=frozenset(documents), progress_id=None,
                            model=None, history="", missing=missing)
    assert asked == [
        ("What does ASME B16.47 say about which flange size range does each standard cover?", ["b"]),
        ("What does ASME B16.5 say about which flange size range does each standard cover?", ["a"])]


# ----------------------------------------------- through the real chat route

def test_the_route_gives_one_side_per_standard_even_when_a_file_carries_an_edition(monkeypatch):
    seen = []

    def fake(side_question, ids, **_kw):
        seen.append(side_question)
        return {"answer_type": "insufficient_evidence", "answer": None, "passages": [],
                "candidates_considered": 0, "reranked": False, "seconds": 0.0}

    monkeypatch.setattr(chat_comparison, "_side_answer", fake)
    client = TestClient(app)
    upload(client, [PWHT_TEMPERATURE], "ASME B16.5-2020.pdf")
    upload(client, [PWHT_TEMPERATURE], "ASME B16.47-2020.pdf")
    convo = client.post("/api/conversations").json()
    body = client.post(f"/api/conversations/{convo['id']}/ask", json={"question": QUESTION}).json()
    assert body["answer_type"] == "comparison"
    names = [s["name"] for s in body["comparison"]["sides"]]
    assert names == ["ASME B16.47", "ASME B16.5"], names
    assert all(s["answer_type"] != "not_in_library" for s in body["comparison"]["sides"])
    assert len(seen) == 2 and all("which flange size range" in q for q in seen)
