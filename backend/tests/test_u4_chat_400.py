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


def test_a_400_names_its_type_and_our_fixed_sentence_in_the_error_and_the_log(lane_open, caplog):
    FakeClient.response = _rejected(400, "max_tokens: 99999 > 64000, which is the maximum allowed number of output tokens for m-1")
    send = reader_transport.transport()
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError) as raised:
        send(URL, headers=HEADERS, body={**BODY, "messages": [{"role": "user", "content": PROMPT_TEXT}]}, timeout=5.0)
    sentence = "max_tokens 99999 is above the model's limit 64000."
    assert str(raised.value) == f"400 from {HOST} (invalid_request_error: {sentence})"
    assert sentence in caplog.text
    assert PROMPT_TEXT not in caplog.text and PROMPT_TEXT not in str(raised.value)


SAFE = [
    ("invalid_request_error", "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.",
     "The Claude account has no credit (the owner tops it up in the Anthropic console)."),
    ("invalid_request_error", "You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.",
     "The Claude account's usage limit is reached; access returns on 2026-12-01."),
    ("invalid_request_error", "max_tokens: 70000 > 64000", "max_tokens 70000 is above the model's limit 64000."),
    ("invalid_request_error", "prompt is too long: 250000 tokens > 200000 maximum",
     "The prompt is too long: 250000 tokens, the model's maximum is 200000."),
    ("rate_limit_error", "whatever the API writes here", "The Claude API is limiting the request rate; try again shortly."),
    ("overloaded_error", "x", "The Claude API is overloaded; try again shortly."),
    ("api_error", "x", "The Claude API had an internal error; try again shortly."),
    ("request_too_large", "x", "The request was too large for the Claude API."),
    ("not_found_error", "model: some-id", "The Claude model was not found (its id may be wrong or retired)."),
]


@pytest.mark.parametrize("kind,message,sentence", SAFE)
def test_each_safe_pattern_gives_our_own_sentence_never_the_apis_words(kind, message, sentence):
    assert reader_transport.api_error({"error": {"type": kind, "message": message}}) == (kind, sentence)
    assert reader_transport.is_fixed_sentence(sentence)


ECHOES = [
    'messages.0.content: got "SECRET DOCUMENT WORDS about the weld procedure"',
    "x-api-key: ABCDEFGHIJKLMNOPQRSTUVWX is invalid",
    "Authorization: " + "Bearer " + "ABCDEFGHIJKLMNOPQRSTUVWX",
    "sk_" + "live_" + "ABCDEFGHIJKLMNOPQRSTUVWX",
    "ABCDEFGHIJKLMNOPQRSTUVWX",
    "max_tokens: 5 > 4 SECRET DOCUMENT WORDS",
    "prompt is too long: 5 tokens > 4 maximum SECRET DOCUMENT WORDS",
]


@pytest.mark.parametrize("message", ECHOES)
def test_an_invalid_request_that_echoes_content_or_a_key_gives_the_type_alone(message, lane_open, caplog):
    assert reader_transport.api_error({"error": {"type": "invalid_request_error", "message": message}}) == ("invalid_request_error", "")
    FakeClient.response = _rejected(400, message)
    send = reader_transport.transport()
    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError) as raised:
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    seen = str(raised.value) + caplog.text + rp.refused_words(rp.ProviderRefused(f"claude: HTTPStatusError: {raised.value}"))
    for fragment in ("SECRET", "ABCDEFGH", "Bearer", "x-api-key", "sk_live", "weld"):
        assert fragment not in seen, fragment
    assert str(raised.value) == f"400 from {HOST} (invalid_request_error)"


def test_authentication_and_permission_errors_give_the_type_alone():
    for status, kind in ((401, "authentication_error"), (403, "permission_error")):
        assert reader_transport.api_error({"error": {"type": kind, "message": "invalid x-api-key sk-1"}}, status) == (kind, "")
    assert reader_transport.api_error("not json at all") == ("", "")
    assert reader_transport.api_error({"error": {"type": "Bad Type!", "message": "m"}}) == ("", "")


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
    _FakeStreamClient.payload = {"error": {"type": "invalid_request_error", "message": "max_tokens: 70000 > 64000"}}
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError) as raised:
        list(reader_transport.stream(URL, headers=HEADERS, body={**BODY, "messages": [{"role": "user", "content": PROMPT_TEXT}]},
                                     timeout=5.0))
    assert "invalid_request_error: max_tokens 70000 is above the model's limit 64000." in str(raised.value)
    assert "limit 64000" in caplog.text and PROMPT_TEXT not in caplog.text


def test_the_screen_reason_carries_the_apis_cause_not_just_the_provider_name(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _ollama(monkeypatch, [])
    cause = "400 from api.anthropic.com (invalid_request_error: max_tokens 5 is above the model's limit 4.)"

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
    assert "400, invalid_request_error; max_tokens 5 is above the model's limit 4." in body["reason"]
    assert body["reason"] != "the answer model would not answer (claude)"


def test_refused_words_never_shows_the_text_of_an_arbitrary_exception():
    for text in ("claude: ValueError: the weld procedure for tag P-101 says SECRET DOCUMENT WORDS",
                 "claude: HTTPStatusError: 400 from api.anthropic.com (invalid_request_error: SECRET DOCUMENT WORDS)",
                 "claude: RuntimeError: Bearer ABCDEFGHIJKLMNOPQRSTUVWX"):
        words = rp.refused_words(rp.ProviderRefused(text))
        assert "SECRET" not in words and "weld" not in words and "Bearer" not in words and "ABCDEFGH" not in words
    assert rp.refused_words(rp.ProviderRefused("claude: ValueError: x")) == (
        "the answer model would not answer (the provider refused the request)")
    assert rp.refused_words(rp.ProviderRefused("claude: HTTPStatusError: 401 from api.anthropic.com (authentication_error)")) == (
        "the answer model would not answer (401, authentication_error)")


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
