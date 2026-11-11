"""A failed answer says WHICH engine failed.

Found 2026-09-30 on the owner's machine: a Claude request failed with a 400 and
the screen said "The local answer model is not running", with an `ollama serve`
tip. The backend reason text was honest; the screen ignored it because the
failed answer carried no engine. Each `model_unavailable` result now stores
`provider` ("claude" or "ollama") so the screen can tell them apart.

Synthetic documents only, no network, no text asserted beyond the engine name.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_answers, chat_model, claude_spend
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from app.rates import Timer
from tests.test_chat import temp_storage, upload  # noqa: F401 - autouse fixture
from tests.test_chat_claude_first import _ask, _on, _tool_use
from tests.test_chat_pr1_model_lane import _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")


def _boom(*_a, **_k):
    raise ConnectionError("unreachable")


def test_a_local_general_failure_names_the_local_engine(monkeypatch):
    monkeypatch.setattr(chat_answers, "_generate", _boom)
    out = chat_answers.general("what is entropy", styles=[], history="", preference="local")
    assert out["answer_type"] == "model_unavailable"
    assert out["provider"] == rp.OLLAMA


def test_a_claude_general_failure_names_claude(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    monkeypatch.setattr(chat_answers, "_generate", _boom)
    out = chat_answers.general("what is entropy", styles=[], history="", preference=None)
    assert out["answer_type"] == "model_unavailable"
    assert out["provider"] == rp.CLAUDE


def test_a_spend_cap_refusal_always_names_claude(monkeypatch):
    def capped(*_a, **_k):
        raise claude_spend.BudgetExceeded("cap")
    monkeypatch.setattr(chat_answers, "_generate", capped)
    out = chat_answers.general("what is entropy", styles=[], history="", preference="local")
    assert out["provider"] == rp.CLAUDE


def test_a_claude_loop_failure_names_claude(monkeypatch, tmp_path):
    """THE MUTATION TARGET: the Claude-first loop's own failure result."""
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    doc = upload(client)
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        n["i"] += 1
        if n["i"] == 1:
            yield from _stream_events(_tool_use("read_document", {"document_id": doc}))
            return
        raise rp.ProviderRefused("claude: HTTPStatusError: 400")

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me about this document", document_id=doc, tier="generated")
    assert body["answer_type"] == "model_unavailable"
    assert body["provider"] == rp.CLAUDE


def test_engine_name_never_raises(monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("no provider")
    monkeypatch.setattr(chat_model, "provider", broken)
    assert chat_model.engine_name(None) == rp.OLLAMA
