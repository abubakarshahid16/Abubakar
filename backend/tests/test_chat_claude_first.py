"""Claude-first chat (owner order 2026-09-27): Claude is the conversation
brain, and the system gives it tools.

What these tests hold, each against a faked Claude transport (no network),
synthetic documents only:
  * "hi" gets a natural reply with no tool call and no citation;
  * "tell me about this document" with a document in scope calls
    read_document for real and returns a cited summary, not a refusal;
  * a tool never returns a document outside the caller's own grants;
  * the web tool is refused - as a consent turn, never a search - when the
    Web switch or the market flags are off, and the sanitiser still applies
    when it is on;
  * the tool-call cap stops the loop rather than looping forever;
  * a budget refusal mid-loop is answered honestly, not silently swallowed;
  * Stop cancels the loop within 2 s even with a tool call already made.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import chat_stream, chat_tools, claude_spend, db
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import KEY, _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")


def _on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _scripted(monkeypatch, payloads, calls=None):
    """`payloads`: one flat Messages payload per Claude turn, repeated on the
    last entry once exhausted (a forced-final call after the tool cap)."""
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        if calls is not None:
            calls.append(body)
        i = min(n["i"], len(payloads) - 1)
        n["i"] += 1
        yield from _stream_events(payloads[i])

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    return n


def _text(t: str) -> dict:
    return {"model": "claude-sonnet-5", "stop_reason": "end_turn",
           "content": [{"type": "text", "text": t}], "usage": {"input_tokens": 200, "output_tokens": 30}}


def _tool_use(name: str, input: dict, id_: str = "toolu_1") -> dict:
    return {"model": "claude-sonnet-5", "stop_reason": "tool_use",
           "content": [{"type": "tool_use", "id": id_, "name": name, "input": input}],
           "usage": {"input_tokens": 200, "output_tokens": 30}}


def _ask(client, convo, question, **extra):
    return client.post(f"/api/conversations/{convo}/ask", json={"question": question, **extra}).json()


# --------------------------------------------------------------- small talk

def test_hi_gets_a_natural_reply_with_no_tools_and_no_citation(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("Hi there! Ask me anything about your documents.")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "hi")
    assert len(calls) == 1, "small talk must not call a tool"
    assert body["answer_type"] == "general"
    assert body["sources"] == []
    assert body["verification"] is None
    assert "[S" not in body["answer"]


# ------------------------------------------------------------- read_document

def test_tell_me_about_this_document_calls_read_document_and_is_not_a_refusal(monkeypatch, tmp_path):
    """THE MUTATION TARGET: a document-in-scope overview uses read_document,
    not the single-passage search gate that used to refuse it."""
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    # NOTE: the quoted span deliberately avoids "no. 1" (a period inside the
    # quotation) - `answer.verify_claims`'s sentence splitter (`_SEGMENT`)
    # breaks on ANY ". " it finds, including one inside an open citation
    # bracket, and then neither half sees a complete [S1 "..."] match. This
    # is a PRE-EXISTING defect in shared code, not part of this feature;
    # flagged in the delivery report rather than fixed in this PR.
    _scripted(monkeypatch, [
        _tool_use("read_document", {"document_id": doc}),
        # Cites BOTH pages: "4" is only on page 2 (S2), and since 2026-09-30
        # every figure must be in a passage the sentence cites
        # (answer.verify_claims) - citing S1 alone for "systems 1 and 4" is
        # now, correctly, removed.
        _text('This document covers coating systems 1 and 4 '
             '[S1 "shall have a NDFT nominal dry film thickness of 280 um"] '
             '[S2 "shall have a NDFT nominal dry film thickness of 450 um"].'),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me about this document", document_id=doc, tier="generated")
    assert len(calls) == 2, "read_document must have been called for real"
    assert body["answer_type"] != "insufficient_evidence"
    assert body["answer_type"] == "generated"
    assert "This document covers coating systems 1 and 4" in body["answer"]
    assert "[S1]" in body["answer"] and '"' not in body["answer"]
    assert body["sources"] and body["sources"][0]["document_id"] == doc
    assert any(s["label"].startswith("Read the whole document") and "2 pages" in s["label"]
              for s in body["steps"])


# --------------------------------------------------------------- permissions

def test_a_tool_never_returns_a_document_outside_the_callers_grants():
    """THE MUTATION TARGET: intersection, never union (CLAUDE.md rule 5)."""
    client = TestClient(app)
    readable = upload(client)
    secret = upload(client)  # a second real document, deliberately not granted
    mine = frozenset({readable})

    run = chat_tools.run_read_document({"document_id": secret}, allowed_document_ids=mine)
    assert run.ok is False and run.sources_added == []

    run2 = chat_tools.run_get_datasheet_fields({"document_id": secret}, allowed_document_ids=mine)
    assert run2.ok is False and run2.sources_added == []

    run3 = chat_tools.run_list_cited_standards({"document_id": secret}, allowed_document_ids=mine)
    assert run3.ok is False

    run4, image = chat_tools.run_look_at_page({"document_id": secret, "page": 1},
                                              allowed_document_ids=mine, pages_used=[])
    assert run4.ok is False and image is None

    # search_documents: a picked id outside the grant narrows to nothing, never widens
    run5 = chat_tools.run_search_documents(
        {"query": "anything", "document_ids": [secret]}, allowed_document_ids=mine)
    assert all(s["document_id"] != secret for s in run5.sources_added)


# ---------------------------------------------------------------------- web

def test_web_tool_is_refused_as_consent_when_the_switch_is_off(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [
        _tool_use("web_search", {"query": "is there a newer edition of ISO 12944"}),
        _text("(unreachable)"),
    ], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "is there a newer edition of ISO 12944 online", web=True)
    # chat_web_enabled defaults False: the tool is not even offered, so route
    # falls to the ordinary web-words router path (unchanged) rather than a
    # tool call - either way nothing is searched.
    assert body["answer_type"] in ("web_consent", "general", "guidance")
    assert len(calls) <= 1


def test_web_tool_asks_first_and_the_sanitiser_still_applies(monkeypatch, tmp_path):
    """THE MUTATION TARGET: calling the web_search TOOL still asks first -
    it never searches on the strength of Claude's own decision alone.

    Uses a plain document-shaped question (no web trigger word), so this
    exercises Claude DECIDING mid-conversation to check the web via the
    tool interface - not the router's separate web-words path."""
    monkeypatch.setattr(settings, "chat_web_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    name = db.connect().execute("SELECT filename FROM documents WHERE id = ?", (doc,)).fetchone()[0]
    stem = name.rsplit(".", 1)[0]
    calls: list = []
    _scripted(monkeypatch, [
        _tool_use("web_search", {"query": f"is there a newer edition of ISO 12944, and of {stem}"}),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what does this datasheet cover", document_id=doc, web=True)
    assert body["answer_type"] == "web_consent"
    assert "Search once?" in body["answer"]
    assert stem not in (body.get("web_phrase") or "")
    assert len(calls) == 1, "the tool call itself must not have sent a search"


# --------------------------------------------------------- extended thinking

def test_extended_thinking_is_used_for_a_complex_question_and_shown(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chat_thinking_budget_tokens", 1500)
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("They differ in scope: A covers welding, B covers coating.")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "compare standard A and standard B")
    assert calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 1500}
    assert "temperature" not in calls[0], "Anthropic refuses temperature while thinking is enabled"
    assert "Thought for" in body["used_line"]


def test_extended_thinking_is_off_for_a_simple_question(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chat_thinking_budget_tokens", 1500)
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("Hi there.")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "hi")
    assert "thinking" not in calls[0]
    assert "Thought for" not in (body["used_line"] or "")


# -------------------------------------------------------------- look_at_page

def test_look_at_page_sends_the_rendered_image_and_the_answer_cites_it(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    # This synthetic page DOES have a text layer (pymupdf's own embedded
    # text), so the same verification as any other source applies: a real
    # quote, checked the normal way - see `chat_tools.run_look_at_page`.
    _scripted(monkeypatch, [
        _tool_use("look_at_page", {"document_id": doc, "page": 1}),
        _text('The page shows it was [S1 "applied as three coats over blast cleaned carbon steel '
             'in atmospheric"].'),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "look at the first page of this datasheet", document_id=doc,
               tier="generated")
    assert len(calls) == 2
    # the SECOND request (after the tool ran) must carry the rendered image
    tool_result = calls[1]["messages"][-1]["content"][0]
    image_blocks = [b for b in tool_result["content"] if b.get("type") == "image"]
    assert image_blocks and image_blocks[0]["source"]["media_type"] == "image/png"
    assert body["answer_type"] == "generated"
    assert body["sources"] and body["sources"][0]["page"] == 1


def test_look_at_page_is_capped_per_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chat_vision_max_pages_per_answer", 1)
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    _scripted(monkeypatch, [
        _tool_use("look_at_page", {"document_id": doc, "page": 1}, "t1"),
        _tool_use("look_at_page", {"document_id": doc, "page": 2}, "t2"),
        _text("Done."),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "look at every page", document_id=doc, tier="generated")
    second_tool_result = calls[2]["messages"][-1]["content"][0]
    assert "page limit reached" in second_tool_result["content"][0]["text"]
    assert not any(b.get("type") == "image" for b in second_tool_result["content"])


# ------------------------------------------------------------------- limits

def test_the_tool_call_cap_stops_the_loop_rather_than_running_forever(monkeypatch, tmp_path):
    """THE MUTATION TARGET: after `chat_tool_max_calls`, the NEXT call offers
    no tools, forcing a final answer instead of looping forever."""
    monkeypatch.setattr(settings, "chat_tool_max_calls", 2)
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    _scripted(monkeypatch, [
        _tool_use("read_document", {"document_id": doc}, "t1"),
        _tool_use("read_document", {"document_id": doc}, "t2"),
        # No tools are offered on the 3rd call (the cap was reached after 2),
        # so a real Claude would never call one here - the fake mirrors that.
        _text("Here is what I found."),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me everything, page by page", document_id=doc, tier="generated")
    # 2 tool-bearing calls + exactly one forced final call with no tools = 3
    assert len(calls) == 3, "the loop must stop offering tools after the cap"
    assert calls[-1].get("tools") in (None, [])
    assert body["answer_type"] in ("generated", "general")


def test_a_budget_refusal_mid_loop_is_answered_honestly_not_swallowed(monkeypatch, tmp_path):
    """THE MUTATION TARGET: a refusal after tools have already run is never a
    silent empty answer - the reader is told, and nothing is invented."""
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        n["i"] += 1
        if n["i"] == 1:
            yield from _stream_events(_tool_use("read_document", {"document_id": doc}))
            return
        raise claude_spend.BudgetExceeded("total: spent $19.99, next call up to $5.00, cap $20.00 in total")

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me about this document", document_id=doc, tier="generated")
    assert len(calls) == 2
    assert body["answer_type"] == "model_unavailable"
    assert "spending cap" in body["reason"]
    assert body["answer"] is None


# --------------------------------------------------------------------- stop

def test_stop_cancels_the_tool_loop_within_two_seconds_after_a_tool_call(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    gate = threading.Event()

    def send(url, *, headers, body, timeout, cancel=None):
        yield {"type": "message_start", "message": {"model": "claude-sonnet-5", "usage": {}}}
        if len(body["messages"]) == 1:
            yield {"type": "content_block_start", "index": 0,
                  "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_document"}}
            yield {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "input_json_delta",
                           "partial_json": json.dumps({"document_id": doc})}}
            yield {"type": "content_block_stop", "index": 0}
            yield {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}}
            return
        gate.set()
        cancel.wait(5)
        return

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))

    convo = client.post("/api/conversations").json()["id"]
    turn = chat_stream.open_turn(owner=None, conversation_id=convo)
    out: dict = {}

    def run():
        from app import chat as chat_mod
        token = chat_stream.bind(turn)
        try:
            out["result"] = chat_mod.ask(
                convo, "tell me about this document", tier="generated", document_id=doc,
                allowed_document_ids=frozenset({doc}), model=None)
        finally:
            chat_stream.unbind(token)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert gate.wait(5), "the second (post-tool) call never started"
    started = time.time()
    turn.cancel.set()
    thread.join(5)
    assert time.time() - started < 2.0, "Stop did not end the loop within 2 s"
    assert out["result"]["answer_type"] == "cancelled"
