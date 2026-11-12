"""The chat's Claude 400 (12 Nov 2026): a 4xx now names its cause (type + short message, never the request) in the log and on
the screen; and what the first send holds when no document is selected is pinned. Invented values; no socket."""
from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app import chat_claude_first, reader_transport
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - autouse fixture
from tests.test_chat_pr1_model_lane import _ask, _ollama
from tests.test_reader_transport import BODY, HEADERS, URL, FakeClient, FakeResponse, lane_open  # noqa: F401
from tests.test_u3_chat_engine import _fake_claude, _lane, _two_documents

HOST = "api.anthropic.com"
PROMPT_TEXT = "SECRET-PROMPT-TEXT-NOT-FOR-LOGS"


def _rejected(status, message, kind="invalid_request_error"):
    return FakeResponse(status=status, payload={"type": "error", "error": {"type": kind, "message": message}})


def test_a_400_names_its_type_and_short_message_in_the_error_and_the_log(lane_open, caplog):
    FakeClient.response = _rejected(400, "max_tokens: 99999 is greater than the model's limit")
    send = reader_transport.transport()
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError) as raised:
        send(URL, headers=HEADERS, body={**BODY, "messages": [{"role": "user", "content": PROMPT_TEXT}]}, timeout=5.0)
    assert str(raised.value) == f"400 from {HOST} (invalid_request_error: max_tokens: 99999 is greater than the model's limit)"
    assert "invalid_request_error: max_tokens" in caplog.text
    assert PROMPT_TEXT not in caplog.text and PROMPT_TEXT not in str(raised.value)


def test_the_message_is_cut_cleaned_and_never_carries_a_key_or_an_auth_message(lane_open):
    FakeClient.response = _rejected(400, "x" * 500 + "\n\tsk-ant-api03-ABCDEF")
    send = reader_transport.transport()
    with pytest.raises(httpx.HTTPStatusError) as raised:
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    message = str(raised.value).split("(invalid_request_error: ", 1)[1].rstrip(")")
    assert len(message) <= reader_transport.ERROR_MESSAGE_CHARS and "\n" not in message
    kind, short = reader_transport.api_error({"error": {"type": "invalid_request_error", "message": "bad sk-ant-api03-ABC key"}})
    assert "sk-ant" not in short and "[key removed]" in short
    assert reader_transport.api_error({"error": {"type": "authentication_error", "message": "invalid x-api-key sk-1"}}, 401) == (
        "authentication_error", "")
    assert reader_transport.api_error("not json at all") == ("", "")
    assert reader_transport.api_error({"error": {"type": "Bad Type!", "message": "m"}}) == ("", "m")


class _FakeStream:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.request = httpx.Request("POST", URL)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()

    def iter_lines(self):
        return iter(())


class _FakeStreamClient:
    status, payload = 400, {}

    def __init__(self, **kw):
        pass

    def stream(self, method, url, headers=None, content=None, extensions=None):
        return _FakeStream(self.status, self.payload)

    def close(self):
        pass


def test_a_streamed_400_names_its_cause_too(monkeypatch, caplog):
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "1")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "1")
    monkeypatch.setattr(httpx, "Client", _FakeStreamClient)
    _FakeStreamClient.payload = {"error": {"type": "invalid_request_error", "message": "messages.0.content: must not be empty"}}
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError) as raised:
        list(reader_transport.stream(URL, headers=HEADERS, body={**BODY, "messages": [{"role": "user", "content": PROMPT_TEXT}]},
                                     timeout=5.0))
    assert "invalid_request_error: messages.0.content: must not be empty" in str(raised.value)
    assert "messages.0.content" in caplog.text and PROMPT_TEXT not in caplog.text


def test_the_screen_reason_carries_the_apis_cause_not_just_the_provider_name(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _ollama(monkeypatch, [])
    cause = "400 from api.anthropic.com (invalid_request_error: max_tokens: too large)"

    def refuse(url, *, headers, body, timeout, cancel=None):
        raise httpx.HTTPStatusError(cause, request=httpx.Request("POST", URL), response=httpx.Response(400))
        yield  # pragma: no cover - makes this a generator like the real stream

    def refuse_once(url, *, headers, body, timeout):
        raise httpx.HTTPStatusError(cause, request=httpx.Request("POST", URL), response=httpx.Response(400))

    class Rejecting(rp.ClaudeProvider):
        def __init__(self, model=None, *, transport=None, step=None, stream_transport=None):
            # BOTH transports are injected: no test may reach the real one.
            super().__init__(model, transport=refuse_once, stream_transport=refuse, step=step)

    monkeypatch.setattr(rp, "ClaudeProvider", Rejecting)
    from app import chat_answers

    body = chat_answers.general("What is the boiling point of water at sea level?", styles=[], history="", preference="claude")
    assert body["answer_type"] == "model_unavailable" and body["provider"] == "claude"
    assert "invalid_request_error: max_tokens: too large" in body["reason"]
    assert len(body["reason"]) < 260
    assert body["reason"] != "the answer model would not answer (claude)"


def test_the_refused_words_are_capped_and_single_line():
    words = rp.refused_words(rp.ProviderRefused("claude: HTTPStatusError: " + "y\n" * 400))
    assert "\n" not in words and len(words) <= 200 + len("the answer model would not answer ()")


# ---------------------------------------- point 4: what the first send holds

def _no_selection_first_send(monkeypatch, tmp_path, *, earlier_document_turn):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen)
    client = TestClient(app)
    first, _ = _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    if earlier_document_turn:
        # a turn that DID quote a document (answered locally, the reader had not chosen Claude)
        _ask(client, convo, "what is the NDFT for coating system no. 1", document_ids=[first])
    seen.clear()
    question = "What is the boiling point of water at sea level?"
    _ask(client, convo, question, model="claude")
    return seen[0], question


def test_the_first_send_with_no_document_selected_is_fixed_text_tools_and_the_question_only(monkeypatch, tmp_path):
    sent, question = _no_selection_first_send(monkeypatch, tmp_path, earlier_document_turn=False)
    assert set(sent) == {"model", "max_tokens", "messages", "tools", "system"}
    assert sent["messages"] == [{"role": "user", "content": question}]
    assert [b["text"] for b in sent["system"]] == [chat_claude_first.SYSTEM_PROMPT]
    assert {t["name"] for t in sent["tools"]} == {
        "search_documents", "read_document", "get_datasheet_fields", "list_cited_standards", "look_at_page"}
    # nothing but the fixed system prompt, the fixed tool definitions and the question: the size is their sum plus JSON syntax
    fixed = json.dumps(sent["tools"]) + chat_claude_first.SYSTEM_PROMPT + question
    assert len(json.dumps(sent, ensure_ascii=False)) <= len(fixed) + 400
    for fragment in ("NDFT", "280", "ZZQ", "777", "spec.pdf", "doc_"):
        assert fragment not in json.dumps(sent), fragment


def test_an_earlier_document_turn_adds_only_the_readers_own_words_never_an_answer(monkeypatch, tmp_path):
    sent, question = _no_selection_first_send(monkeypatch, tmp_path, earlier_document_turn=True)
    content = sent["messages"][0]["content"]
    assert content.endswith(f"Question: {question}")
    assert "Assistant:" not in content, "an earlier answer (which quotes a document) was sent"
    for fragment in ("280", "nominal dry film", "ZZQ", "777", "spec.pdf"):
        assert fragment not in json.dumps(sent), fragment


def test_the_settings_the_old_shape_needs_are_still_what_the_request_builder_uses():
    assert settings.claude_reasoning_model  # the one setting the chat's model comes from
