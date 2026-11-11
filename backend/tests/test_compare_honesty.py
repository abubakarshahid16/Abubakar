"""Chat comparison honesty (2026-10-01, audit entry 99).

Owner's screen after the compare feature shipped: side A "Not found in the
pages read.", side B a bulleted answer with five sources, header "Checked 1
standard" (a two-sided compare), and citation markers that looked wrong.

Three things are pinned here, all on synthetic data (no documents, no model):

  1. The header says what a compare REALLY searched, from the per-side
     results: "Searched 2 standards, found text in 1".
  2. Every in-text [S#] resolves to the matching entry of the source list the
     API returns, whichever side is empty, with repeats and multi-digit numbers.
  3. "Not found in the pages read" is written only for a side whose OWN
     search ran.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import chat_comparison, chat_presentation
from app.main import app
from tests.test_chat_comparison import PWHT_TEMPERATURE, temp_storage, upload  # noqa: F401

A_DOC, B_DOC = "doc-a", "doc-b"
_STANDARD = {"document_role": "COMPANY_STANDARD"}


@pytest.fixture(autouse=True)
def _roles(monkeypatch):
    monkeypatch.setattr(
        chat_presentation, "_roles",
        lambda ids: {i: {"id": i, "filename": f"{i}.pdf", **_STANDARD} for i in ids})


def _passage(doc: str, n: int) -> dict:
    return {"document_id": doc, "chunk_id": f"{doc}:{n}", "page_start": n, "page_end": n,
            "text": f"text {doc} {n}", "section": None}


def _generated(text: str, passages: list[dict]) -> dict:
    return {"answer_type": "generated", "answer": text, "passages": passages,
            "candidates_considered": 3, "reranked": True, "seconds": 1.0}


_EMPTY = {"answer_type": "insufficient_evidence", "answer": None, "passages": []}


def _compare(monkeypatch, a: dict, b: dict, *, allowed=frozenset({A_DOC, B_DOC}),
             missing=None, question="compare STD-A-001 against STD-B-002 on welding") -> dict:
    monkeypatch.setattr(chat_comparison, "_side_answer",
                        lambda q, ids, **_kw: a if A_DOC in ids else b)
    return chat_comparison.compare(
        question, [("STD-A-001", frozenset({A_DOC})), ("STD-B-002", frozenset({B_DOC}))],
        tier="generated", allowed_document_ids=allowed, progress_id=None, model=None,
        history="", missing=missing)


def _check_citations(out: dict) -> None:
    """Every [S#] in each side's text names the entry of the API's own source
    list (`chat_presentation.sources`) that belongs to THAT side."""
    sources = chat_presentation.sources(out)
    assert [s["n"] for s in sources] == list(range(1, len(sources) + 1))
    for side in out["comparison"]["sides"]:
        own = {side["source_start"] + k + 1 for k in range(side["source_count"])}
        cited = [int(n) for n in re.findall(r"\[S(\d+)\]", side["text"] or "")]
        for n in cited:
            assert n in own, f"{side['name']} cites [S{n}], outside its own sources {sorted(own)}"
            doc = sources[n - 1]["document_id"]
            assert doc in side["document_ids"], f"[S{n}] resolves to another side's document"


# ------------------------------------------------------------ 1. the header


def test_header_counts_searched_sides_not_only_the_ones_that_found_text(monkeypatch):
    out = _compare(monkeypatch, _EMPTY, _generated("Bravo [S1].", [_passage(B_DOC, 1)]))
    assert chat_presentation.used_line(out).startswith("Searched 2 standards, found text in 1")
    assert "Checked" not in chat_presentation.used_line(out)


def test_header_when_both_sides_found_text(monkeypatch):
    out = _compare(monkeypatch, _generated("A [S1].", [_passage(A_DOC, 1)]),
                   _generated("B [S1].", [_passage(B_DOC, 1)]))
    assert chat_presentation.used_line(out).startswith("Searched 2 standards, found text in 2")


def test_header_when_neither_side_found_text_says_none_never_zero(monkeypatch):
    out = _compare(monkeypatch, _EMPTY, _EMPTY)
    line = chat_presentation.used_line(out)
    assert line.startswith("Searched 2 standards, found text in none")
    assert " 0" not in line


def test_header_does_not_count_a_side_that_was_never_searched(monkeypatch):
    out = _compare(monkeypatch, _generated("A [S1].", [_passage(A_DOC, 1)]), _EMPTY,
                   allowed=frozenset({A_DOC}))
    line = chat_presentation.used_line(out)
    assert line.startswith("Searched 1 standard, found text in 1")
    assert "not among those you can read" in line


def test_header_names_a_typed_standard_the_library_does_not_hold(monkeypatch):
    out = _compare(monkeypatch, _generated("A [S1].", [_passage(A_DOC, 1)]),
                   _generated("B [S1].", [_passage(B_DOC, 1)]), missing=["ZZZ-999-X"])
    line = chat_presentation.used_line(out)
    assert line.startswith("Searched 2 standards, found text in 2")
    assert "1 named document not among those you can read" in line


def test_ordinary_and_single_document_headers_are_unchanged():
    one = {"answer_type": "generated", "passages": [_passage(A_DOC, 1), _passage(A_DOC, 2)]}
    assert chat_presentation.used_line(one) == "Checked 1 standard"
    two = {"answer_type": "generated", "passages": [_passage(A_DOC, 1), _passage(B_DOC, 2)]}
    assert chat_presentation.used_line(two) == "Checked 2 standards"
    extract = {"answer_type": "extract", "passage": _passage(A_DOC, 3)}
    assert chat_presentation.used_line(extract) == "Checked 1 standard"
    assert chat_presentation.used_line({"answer_type": "generated", "passages": []}) \
        == "Searched your documents · nothing found that answers this"


# ------------------------------------------------------- 2. citation numbers


def test_side_a_empty_side_b_citations_match_the_source_list(monkeypatch):
    out = _compare(monkeypatch, _EMPTY, _generated(
        "- **Heat** is applied [S1].\n- Hold time [S2] and [S3].",
        [_passage(B_DOC, 4), _passage(B_DOC, 5), _passage(B_DOC, 6)]))
    a, b = out["comparison"]["sides"]
    assert a["source_count"] == 0 and b["source_start"] == 0
    assert "[S1]" in b["text"] and "[S3]" in b["text"]
    _check_citations(out)
    assert [s["page"] for s in chat_presentation.sources(out)] == [4, 5, 6]


def test_side_b_empty_side_a_citations_match_the_source_list(monkeypatch):
    out = _compare(monkeypatch, _generated("Alpha [S1] [S2].", [_passage(A_DOC, 1), _passage(A_DOC, 2)]),
                   _EMPTY)
    _check_citations(out)
    assert len(chat_presentation.sources(out)) == 2


def test_both_sides_with_passages_each_resolve_to_their_own_sources(monkeypatch):
    out = _compare(monkeypatch,
                   _generated("Alpha [S1], [S2].", [_passage(A_DOC, 1), _passage(A_DOC, 2)]),
                   _generated("Bravo [S1], [S2], [S3].",
                              [_passage(B_DOC, 7), _passage(B_DOC, 8), _passage(B_DOC, 9)]))
    b = out["comparison"]["sides"][1]
    assert b["source_start"] == 2
    assert [n for n in re.findall(r"\[S(\d+)\]", b["text"])] == ["3", "4", "5"]
    _check_citations(out)
    assert chat_presentation.sources(out)[2]["page"] == 7


def test_repeated_citations_of_one_source_are_all_moved(monkeypatch):
    out = _compare(monkeypatch,
                   _generated("Alpha [S1].", [_passage(A_DOC, 1)]),
                   _generated("Bravo [S1] first, [S1] again, then [S2].",
                              [_passage(B_DOC, 7), _passage(B_DOC, 8)]))
    b = out["comparison"]["sides"][1]
    assert b["text"] == "Bravo [S2] first, [S2] again, then [S3]."
    _check_citations(out)


def test_multi_digit_citation_numbers_are_moved_whole(monkeypatch):
    a_passages = [_passage(A_DOC, i) for i in range(1, 12)]      # 11 passages
    b_passages = [_passage(B_DOC, i) for i in range(1, 13)]      # 12 passages
    out = _compare(monkeypatch,
                   _generated("Alpha [S11] and [S1].", a_passages),
                   _generated("Bravo [S1], [S10], [S12].", b_passages))
    b = out["comparison"]["sides"][1]
    assert b["text"] == "Bravo [S12], [S21], [S23]."
    _check_citations(out)
    assert chat_presentation.sources(out)[22]["document_id"] == B_DOC


# ----------------------------------------------------------- 3. absence text


def test_not_found_is_written_only_for_a_side_whose_own_search_ran(monkeypatch):
    calls: list = []

    def fake_answer(question, **kw):
        calls.append(kw["allowed_document_ids"])
        return dict(_EMPTY)

    monkeypatch.setattr(chat_comparison.answer_mod, "answer", fake_answer)
    out = chat_comparison.compare(
        "compare STD-A-001 against STD-B-002 on welding",
        [("STD-A-001", frozenset({A_DOC})), ("STD-B-002", frozenset({B_DOC}))],
        tier="generated", allowed_document_ids=frozenset({A_DOC}), progress_id=None,
        model=None, history="")
    a, b = out["comparison"]["sides"]
    assert calls == [frozenset({A_DOC})], "the unreadable side must not reach retrieval"
    assert a["searched"] is True and a["text"] == "STD-A-001: not found in the pages read."
    assert b["searched"] is False and b["answer_type"] == "not_in_library"
    assert "not found in the pages read" not in b["text"]
    assert b["text"] == "STD-B-002: not among the documents you can read."
    assert "STD-B-002: not found" not in out["answer"]


def test_a_typed_but_absent_standard_is_never_called_not_found(monkeypatch):
    out = _compare(monkeypatch, _generated("A [S1].", [_passage(A_DOC, 1)]),
                   _generated("B [S1].", [_passage(B_DOC, 1)]), missing=["ZZZ-999-X"])
    last = out["comparison"]["sides"][-1]
    assert last["searched"] is False
    assert "not found in the pages read" not in last["text"]


# ------------------------------------------------------------- end to end


def test_the_route_returns_the_honest_header_and_the_searched_flag():
    """Through `chat.ask` and the response schema: `searched` must survive
    serialisation, and the header must count the one side really searched."""
    client = TestClient(app, raise_server_exceptions=True)
    upload(client, [PWHT_TEMPERATURE], "SAES-W-010.pdf")
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "compare SAES-W-010 against ZZZ-999-X on the post weld heat "
                          "treatment temperature"},
    ).json()
    assert body["answer_type"] == "comparison"
    by_name = {s["name"]: s for s in body["comparison"]["sides"]}
    assert by_name["SAES-W-010"]["searched"] is True
    assert by_name["ZZZ-999-X"]["searched"] is False
    assert body["used_line"].startswith("Searched 1 ")
    assert "found text in 1" in body["used_line"]
    assert "not among those you can read" in body["used_line"]
