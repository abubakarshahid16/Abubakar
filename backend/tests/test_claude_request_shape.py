"""Claude chat loop: the SHAPE of every request must satisfy the Messages API.

Why this file exists (found 2026-09-30 on the owner's machine, real Claude):
a question that makes Claude search several times answered
"claude: HTTPStatusError: 400 ... (invalid_request_error)". The spend ledger
(costs and timings only) showed 2-3 calls settling normally and then one call
failing in under a second. The fake transport in test_chat_claude_first.py
never checked what it was sent, so the loop passed every test while sending
requests the real API refuses.

Two rules of the real API, checked here on every request body the loop sends
(synthetic documents only, no network, no text asserted):

  R1. A request whose messages contain `tool_use` or `tool_result` blocks must
      define `tools`. The tool-call cap used to send `tools=()`.
  R2. A `thinking` block sent back must carry its `signature` (the streamed
      `signature_delta` was dropped), and thinking must stay enabled for the
      rest of a tool-use turn (it was switched off after round 1).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _ask, _on, _text, _tool_use
from tests.test_chat_pr1_model_lane import _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")


def _blocks(body: dict):
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    yield message.get("role"), block


def shape_problems(body: dict) -> list[str]:
    """Structural rules only: block types and presence, never text."""
    problems: list[str] = []
    kinds = {block.get("type") for _role, block in _blocks(body)}
    if kinds & {"tool_use", "tool_result"} and not body.get("tools"):
        problems.append("R1: tool_use/tool_result in messages but no tools defined")
    for role, block in _blocks(body):
        if block.get("type") == "thinking":
            if not block.get("signature"):
                problems.append("R2: a thinking block was sent back without its signature")
            if not (body.get("thinking") or {}).get("type") == "enabled":
                problems.append("R2: a thinking block is in messages but thinking is not enabled")
    return problems


def _scripted_events(monkeypatch, scripts, calls):
    """`scripts`: one list of raw SSE events per call, the last repeated."""
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        i = min(n["i"], len(scripts) - 1)
        n["i"] += 1
        yield from scripts[i]

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))


def _thinking_then_tool(tool_name: str, input: dict, id_: str) -> list[dict]:
    """What the real API streams: a thinking block with thinking_delta then a
    signature_delta, then a tool_use block."""
    return [
        {"type": "message_start", "message": {"model": "claude-sonnet-5", "usage": {}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "work it out"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "sig-abc"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": id_, "name": tool_name}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": json.dumps(input)}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"input_tokens": 200, "output_tokens": 30}},
    ]


def test_every_request_after_the_tool_cap_still_defines_tools(monkeypatch, tmp_path):
    """THE MUTATION TARGET (R1): the call made after `chat_tool_max_calls` is
    reached keeps `tools` defined, because the history holds tool blocks."""
    monkeypatch.setattr(settings, "chat_tool_max_calls", 2)
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    n = {"i": 0}
    payloads = [_tool_use("read_document", {"document_id": doc}, "t1"),
                _tool_use("read_document", {"document_id": doc}, "t2"),
                _text("Here is what I found.")]

    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        i = min(n["i"], len(payloads) - 1)
        n["i"] += 1
        yield from _stream_events(payloads[i])

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "tell me everything, page by page", document_id=doc, tier="generated")
    assert len(calls) == 3
    assert [shape_problems(b) for b in calls] == [[], [], []]


def test_a_thinking_turn_with_a_tool_call_sends_a_valid_second_request(monkeypatch, tmp_path):
    """THE MUTATION TARGET (R2): round 1 thinks and calls a tool; round 2 must
    send the thinking block back WITH its signature and with thinking on."""
    monkeypatch.setattr(settings, "chat_thinking_budget_tokens", 1500)
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    _scripted_events(monkeypatch, [
        _thinking_then_tool("read_document", {"document_id": doc}, "t1"),
        list(_stream_events(_text("Done."))),
    ], calls)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "compare standard A and standard B", document_id=doc, tier="generated")
    assert len(calls) == 2
    assert calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 1500}
    assert shape_problems(calls[1]) == []
