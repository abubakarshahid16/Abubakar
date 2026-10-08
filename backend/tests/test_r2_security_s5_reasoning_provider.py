"""r2 S5: CLAUDE.md says Claude is off unless REASONING_PROVIDER=claude AND both
reader flags AND a key. The four `claude_api` review routes checked only the
two flags, so REASONING_PROVIDER=ollama with the flags and a key set still
sent document text to Claude. Mutations: scripts/mutations/r2_security.py M1986.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, claude_api, datasheet_ai, db, submittal_review
from app.config import settings
from app.main import app

ROUTES = [
    ("post", "/api/reviews/runs/run-x/claude/select-standards"),
    ("post", "/api/reviews/runs/run-x/claude/read-datasheet"),
    ("post", "/api/reviews/runs/run-x/claude/recheck"),
    ("post", "/api/reviews/runs/run-x/claude/crs-draft"),
]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "p.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    # Everything else that would let Claude through is ON; only the provider
    # decides these tests.
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-invented-key")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    app.dependency_overrides.clear()
    db.reset_connection()


def _fake_transport(monkeypatch):
    sent = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        raise AssertionError("a request left the machine")
    send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport", lambda: send)
    return sent


@pytest.mark.parametrize("provider", ["ollama", "", "off"])
@pytest.mark.parametrize("method,path", ROUTES)
def test_a_review_route_refuses_when_the_provider_is_not_claude(
        method, path, provider, monkeypatch):
    sent = _fake_transport(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    monkeypatch.setattr(claude_api, "_run_or_404",
                        lambda rid, scope: {"id": "run-x", "submittal_document_id": "doc-1"})
    monkeypatch.setattr(claude_api, "_datasheet_summary", lambda sid, scope: {"text": "x"})
    from app import main
    monkeypatch.setattr(main, "_crs_content", lambda *a, **k: ([], {}, "sub.pdf", "stamp"))
    response = getattr(TestClient(app), method)(path)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == claude_api.MODEL_DISABLED
    assert sent == []


def test_the_model_call_is_built_only_for_provider_claude(monkeypatch):
    _fake_transport(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    with pytest.raises(Exception) as caught:
        claude_api._model_call_or_409(claude_api.STEP_RECHECK)
    assert caught.value.status_code == 409
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    model_call, _transport = claude_api._model_call_or_409(claude_api.STEP_RECHECK)
    assert callable(model_call)


def test_the_datasheet_reader_also_needs_provider_claude(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    call, reason = datasheet_ai.model_call_for("claude")
    assert call is None and "PROVIDER_OFF" in reason, reason
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    call, reason = datasheet_ai.model_call_for("claude")
    assert call is not None, reason
