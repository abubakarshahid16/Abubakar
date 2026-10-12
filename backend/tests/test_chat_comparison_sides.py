"""Chat comparison, the side-by-side contract (found 2026-10-01 on the owner's
machine with real "Written explanation" answers).

Four defects in what shipped in the first comparison PR, none caught because
every test used the quotation tier, whose text is one short paragraph:

  1. A side's written text with a blank line in it shifted every later side's
     text on the screen (the screen split the combined text on blank lines).
  2. The second side's [S1] pointed at the FIRST side's passage.
  3. A compare naming a standard the library does not hold fell through to a
     search that could not say one of the two was never there.
  4. "compare A and B" with no topic searched each side for nothing and then
     reported "not found in the pages read" - a claim about a search that never
     had anything to look for - and the model, shown "compare B", said no
     second standard had been named.

Synthetic data only. `_side_answer` is replaced so the assembly is tested on
its own; no documents, no model, no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_comparison
from app.main import app
from tests.test_chat_comparison import (  # noqa: F401
    PWHT_TEMPERATURE,
    SCOPE_ONLY,
    temp_storage,
    upload,
)

A_DOC, B_DOC = "doc-a", "doc-b"


def _passage(doc: str, n: int) -> dict:
    return {"document_id": doc, "chunk_id": f"{doc}:{n}", "page_start": n, "page_end": n,
            "text": f"text {doc} {n}", "section": None}


def _generated(text: str, passages: list[dict]) -> dict:
    return {"answer_type": "generated", "answer": text, "passages": passages,
            "candidates_considered": 3, "reranked": True, "seconds": 1.0}


def _compare(monkeypatch, answers: dict[str, dict], question: str, *,
             sides=None, missing=None, seen: list | None = None) -> dict:
    def fake(side_question, ids, **_kw):
        if seen is not None:
            seen.append(side_question)
        key = "a" if A_DOC in ids else "b"
        return answers[key]

    monkeypatch.setattr(chat_comparison, "_side_answer", fake)
    sides = sides or [("STD-A-001", frozenset({A_DOC})), ("STD-B-002", frozenset({B_DOC}))]
    return chat_comparison.compare(
        question, sides, tier="generated", allowed_document_ids=frozenset({A_DOC, B_DOC}),
        progress_id=None, model=None, history="", missing=missing)


def test_each_side_keeps_its_own_multi_paragraph_text(monkeypatch):
    out = _compare(monkeypatch, {
        "a": _generated("Alpha opening.\n\nAlpha second [S1].", [_passage(A_DOC, 4)]),
        "b": _generated("Bravo only [S1].", [_passage(B_DOC, 9)]),
    }, "compare STD-A-001 and STD-B-002 on welding")
    a, b = out["comparison"]["sides"]
    assert "Alpha opening." in a["text"] and "Alpha second" in a["text"]
    assert "Alpha" not in b["text"] and "Bravo only" in b["text"]


def test_the_second_sides_citations_point_past_the_first_sides_passages(monkeypatch):
    """THE MUTATION TARGET (defect 2)."""
    out = _compare(monkeypatch, {
        "a": _generated("Alpha [S1] and [S2].", [_passage(A_DOC, 1), _passage(A_DOC, 2)]),
        "b": _generated("Bravo [S1].", [_passage(B_DOC, 7)]),
    }, "compare STD-A-001 and STD-B-002 on welding")
    a, b = out["comparison"]["sides"]
    assert a["source_start"] == 0 and a["source_count"] == 2
    assert b["source_start"] == 2 and b["source_count"] == 1
    assert "[S3]" in b["text"] and "[S1]" not in b["text"]
    # and the numbered passage list agrees: [S3] is side B's own passage
    assert out["passages"][2]["document_id"] == B_DOC


def test_a_side_with_nothing_found_takes_no_sources_and_the_next_side_starts_at_zero(monkeypatch):
    out = _compare(monkeypatch, {
        "a": {"answer_type": "insufficient_evidence", "answer": None, "passages": []},
        "b": _generated("Bravo [S1].", [_passage(B_DOC, 7)]),
    }, "compare STD-A-001 and STD-B-002 on welding")
    a, b = out["comparison"]["sides"]
    assert a["source_count"] == 0 and a["text"].endswith("not found in the pages read.")
    assert b["source_start"] == 0 and "[S1]" in b["text"]


def test_a_standard_typed_but_not_in_the_library_is_reported_as_such(monkeypatch):
    """THE MUTATION TARGET (defect 3): written in code, never searched."""
    seen: list = []
    out = _compare(monkeypatch, {"a": _generated("Alpha [S1].", [_passage(A_DOC, 1)])},
                   "compare STD-A-001 and ASME B31.3 on welding",
                   sides=[("STD-A-001", frozenset({A_DOC}))], missing=["B31.3"], seen=seen)
    sides = out["comparison"]["sides"]
    assert [s["answer_type"] for s in sides] == ["generated", "not_in_library"]
    assert sides[1]["text"] == "B31.3: not among the documents you can read."
    assert len(seen) == 1, "a standard that is not in the library must not be searched"


def test_missing_designations_only_flags_a_typed_standard_with_a_digit():
    q = "compare SAES-W-016 and ASME B31.3 on post-weld heat treatment of 10-inch H2S-service pipe"
    assert chat_comparison.missing_designations(q, ["SAES-W-016"]) == ["B31.3"]
    assert chat_comparison.missing_designations("compare saes-w-016 and b31.3", ["SAES-W-016"]) == []
    assert chat_comparison.missing_designations(q, ["SAES-W-016", "B31.3"]) == []


def test_a_comparison_with_no_topic_asks_what_to_compare_and_searches_nothing(monkeypatch):
    """THE MUTATION TARGET (defect 4)."""
    seen: list = []
    out = _compare(monkeypatch, {"a": _generated("x", []), "b": _generated("y", [])},
                   "compare STD-A-001 and STD-B-002", seen=seen)
    assert out["answer_type"] == "guidance"
    assert "on what" in out["answer"].lower()
    assert seen == [], "nothing may be searched, so nothing may be reported as not found"


def test_each_sides_question_names_its_own_standard_and_the_topic_only(monkeypatch):
    seen: list = []
    _compare(monkeypatch, {
        "a": _generated("Alpha [S1].", [_passage(A_DOC, 1)]),
        "b": _generated("Bravo [S1].", [_passage(B_DOC, 1)]),
    }, "compare STD-A-001 and STD-B-002 on post weld heat treatment", seen=seen)
    assert len(seen) == 2
    assert "STD-A-001" in seen[0] and "STD-B-002" not in seen[0]
    assert "STD-B-002" in seen[1] and "STD-A-001" not in seen[1]
    for q in seen:
        assert "post weld heat treatment" in q
        assert "compare" not in q.lower()


@pytest.mark.parametrize("question,expected", [
    ("compare STD-A-001 and STD-B-002 on post weld heat treatment", "post weld heat treatment"),
    ("compare STD-A-001 and STD-B-002 about hydrotest", "hydrotest"),
    ("STD-A-001 versus STD-B-002 for flange rating", "flange rating"),
    ("compare STD-A-001 and STD-B-002", None),
    ("compare STD-A-001 with STD-B-002.", None),
    ("compare STD-A-001 against STD-B-002", None),
    ("compare STD-A-001 from STD-B-002", None),
    ("compare STD-A-001 against STD-B-002 on hydrotest", "hydrotest"),
])
def test_topic_of(question, expected):
    assert chat_comparison.topic_of(question, ["STD-A-001", "STD-B-002"]) == expected


# --------------------------------------------------------------- end to end


def test_the_route_reports_a_standard_the_library_does_not_hold():
    """Wired through `chat.ask`: one standard indexed, one typed but absent."""
    client = TestClient(app)
    upload(client, [PWHT_TEMPERATURE], "SAES-W-010.pdf")
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "compare SAES-W-010 and ZZZ-999-X on the post weld heat "
                          "treatment temperature"},
    ).json()
    assert body["answer_type"] == "comparison"
    by_name = {s["name"]: s for s in body["comparison"]["sides"]}
    assert by_name["ZZZ-999-X"]["answer_type"] == "not_in_library"
    assert by_name["ZZZ-999-X"]["document_ids"] == []
    assert by_name["SAES-W-010"]["source_count"] >= 1
    assert "620" in body["answer"]


def test_the_route_asks_what_to_compare_when_no_topic_is_given():
    client = TestClient(app)
    upload(client, [PWHT_TEMPERATURE], "SAES-W-010.pdf")
    upload(client, [SCOPE_ONLY], "ASME-B31-3.pdf")
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "compare SAES-W-010 against ASME-B31-3"},
    ).json()
    assert body["answer_type"] == "guidance"
    assert "on what" in (body["answer"] or "").lower()
    assert body.get("comparison") in (None, {}) or not body["comparison"]["sides"]
