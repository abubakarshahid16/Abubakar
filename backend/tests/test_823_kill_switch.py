"""Q42 / #823: the code half of docs/security/kill-switch.md really works.

The drill (close sessions, revoke the GitHub token) is the owner's. Step 3 of
the document is a claim about the code: remove the Claude API key, or set
REASONING_PROVIDER=ollama, and no step can reach the Claude lane any more.
Everything that would let Claude through is switched ON below; only the one
kill-switch action changes. No network, no document text, an invented key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import datasheet_ai, reader_api, reasoning_provider
from app.config import settings

DOC = Path(__file__).resolve().parents[2] / "docs" / "security" / "kill-switch.md"


@pytest.fixture(autouse=True)
def _claude_fully_on(monkeypatch):
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv(reader_api.API_KEY_ENV, "sk-ant-test-invented-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")


def _every_route_is_closed():
    assert reasoning_provider.claude_unavailable()[0] is not None
    assert reasoning_provider.claude_unavailable_for_task("claude")[0] is not None
    assert reasoning_provider.claude_for_task("claude") is None
    assert isinstance(reasoning_provider.get_provider(), reasoning_provider.OllamaProvider)
    call, why = datasheet_ai._claude_call()
    assert call is None and "unavailable" in why


def test_the_fixture_really_leaves_the_lane_open():
    assert reasoning_provider.claude_unavailable()[0] is None
    assert reasoning_provider.claude_unavailable_for_task("claude")[0] is None
    assert reasoning_provider.claude_lane_open() is True


@pytest.mark.parametrize("provider", ["ollama", "", "off"])
def test_setting_the_provider_to_ollama_closes_every_route(monkeypatch, provider):
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    _every_route_is_closed()
    assert reasoning_provider.claude_unavailable()[0] == reasoning_provider.UNAVAILABLE_PROVIDER_OFF
    code = reasoning_provider.claude_unavailable_for_task("claude")[0]
    assert code == reasoning_provider.UNAVAILABLE_PROVIDER_OFF


def test_removing_the_api_key_closes_every_route(monkeypatch):
    monkeypatch.delenv(reader_api.API_KEY_ENV)
    _every_route_is_closed()
    assert reasoning_provider.claude_unavailable()[0] == reasoning_provider.UNAVAILABLE_KEY_MISSING
    assert reasoning_provider.claude_lane_open() is False


def test_the_provider_switch_beats_a_step_that_says_claude(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    assert reasoning_provider.claude_unavailable_for_task("claude")[0] is None
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert reasoning_provider.claude_unavailable_for_task("claude")[0] is not None


def test_the_document_names_switches_that_exist():
    text = DOC.read_text(encoding="utf-8")
    assert "REASONING_PROVIDER=ollama" in text
    assert hasattr(settings, "reasoning_provider") and hasattr(settings, "anthropic_api_key")
    assert reader_api.API_KEY_ENV == "ANTHROPIC_API_KEY"
    assert "Claude API key" in text and "backend/.env" in text
