"""#454 (audit B04): a tool-only answer keeps its document ids.

`list_cited_standards` looked up each held standard's document id and threw
it away, returning text only. An answer from that tool alone had no sources,
so `_finish` dropped every citation and typed it "general knowledge". Now the
tool returns the submittal's printed line and page for each citation, plus
each held standard's first passage, all with document ids the caller may read.
Synthetic documents only; the model is not called.

Mutations: M6601-M6606 (scripts/mutations/w3_454_tool_answer_ids.py).
"""
from __future__ import annotations

import time

from app import chat_claude_first, chat_tools
from app import reasoning_provider as rp
from tests.test_standard_matcher import _doc, temp_storage  # noqa: F401

TEXT = "Relief valve sizing per API RP 520 Pt-1 and API 650."


def _setup():
    std = _doc("std_520_1", "API-520-I.pdf", "COMPANY_STANDARD", text="API 520 Part I sizing of relief devices.")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL", text=TEXT)
    return std, sub


def test_the_cited_standards_tool_returns_sources_with_document_ids(temp_storage):
    """THE MUTATION TARGET: before #454 `sources_added` was empty."""
    std, sub = _setup()
    run = chat_tools.run_list_cited_standards({"document_id": sub},
                                              allowed_document_ids=frozenset({std, sub}))
    assert run.ok and run.sources_added, "the tool returned no sources"
    by_doc = {}
    for s in run.sources_added:
        by_doc.setdefault(s["document_id"], []).append(s)
    # Every citation in the submittal: its own page and printed line.
    cites = by_doc[sub]
    assert {s["section"] for s in cites} == {"cites API RP 520 Pt-1", "cites API 650"}
    assert all(s["page_start"] == 1 and s["text"] and "API" in s["text"] for s in cites)
    # The held standard, by its own document id.
    assert [s["filename"] for s in by_doc[std]] == ["API-520-I.pdf"]


def test_every_source_is_a_document_the_caller_may_read(temp_storage):
    std, sub = _setup()
    run = chat_tools.run_list_cited_standards({"document_id": sub}, allowed_document_ids=frozenset({sub}))
    assert {s["document_id"] for s in run.sources_added} == {sub}
    assert "API RP 520 Pt-1: cited but not held in this library" in run.note


def test_a_citation_with_no_page_gets_no_source_never_a_guessed_page(temp_storage, monkeypatch):
    std, sub = _setup()
    from app import applicability
    monkeypatch.setattr(applicability, "citation_evidence", lambda *a, **k: (None, None))
    run = chat_tools.run_list_cited_standards({"document_id": sub},
                                              allowed_document_ids=frozenset({std, sub}))
    assert all(s["document_id"] != sub for s in run.sources_added)


def test_a_tool_only_answer_is_a_cited_document_answer_not_general_knowledge(temp_storage):
    std, sub = _setup()
    run = chat_tools.run_list_cited_standards({"document_id": sub},
                                              allowed_document_ids=frozenset({std, sub}))
    n = next(i for i, s in enumerate(run.sources_added, start=1) if s["section"] == "cites API 650")
    response = rp.Response(text=f"Relief valve sizing is per API 650 [S{n} \"sizing per API RP 520 Pt-1 and API 650\"].", provider=rp.CLAUDE,
                           model_tag="fake", digest="d", finish_reason="stop", prompt_sha256="x",
                           schema_errors=[], cost_usd=0.0)
    result = chat_claude_first._finish(response, list(run.sources_added), [], time.time(), None,
                                       question="which standards does it cite")
    assert result["answer_type"] == "generated"
    assert result["input_kind"] == "document"
    assert f"[S{n}]" in result["answer"]
    assert result["passages"][n - 1]["document_id"] == sub


def test_a_held_standard_outside_the_grants_is_never_a_source(temp_storage):
    """Defence in depth: even if a held list ever names a standard the caller
    cannot read, it never becomes a source."""
    std, sub = _setup()
    doc = chat_tools._readable(sub, allowed_document_ids=frozenset({sub}))
    sources = chat_tools._cited_standard_sources(
        doc, sub, [], [{"identifier": "API 520", "standard_document_id": std, "filename": "API-520-I.pdf"}],
        allowed_document_ids=frozenset({sub}))
    assert sources == []
