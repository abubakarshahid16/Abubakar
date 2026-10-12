"""Vision reader status: the line beside "Read unread pages".

The claim under test: the screen can say, BEFORE a click, whether page images
will be read and, if not, the real reason - and that answer never carries the
API key. No network: `reader_transport.list_models` is replaced throughout,
and every test that reaches it plants a fake key to prove it never leaks.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import claude_spend, reader_transport, vision_reader
from app.config import settings

FAKE_KEY = "fake-key-NEVER-SHOWN-0123456789"


@pytest.fixture(autouse=True)
def _all_local_checks_pass(monkeypatch):
    """Every local condition met, spend at zero, a fresh cache. A test turns
    ONE condition off to show that state."""
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(claude_spend, "spent", lambda step=None: 0.0)
    vision_reader._status_cache.clear()
    yield
    vision_reader._status_cache.clear()


def _no_network(**_kw):
    raise AssertionError("a local check must answer without calling Claude")


def _assert_no_secret(result: dict) -> None:
    assert FAKE_KEY not in json.dumps(result)


def test_geometry_switch_off_is_named_and_needs_no_network(monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(reader_transport, "list_models", _no_network)

    result = vision_reader.reader_status()

    assert result["state"] == "GEOMETRY_OFF" and result["ready"] is False
    assert "GEOMETRY_READER_ENABLED=true" in result["fix"]


def test_missing_key_is_named_and_needs_no_network(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(reader_transport, "list_models", _no_network)

    result = vision_reader.reader_status()

    assert result["state"] == "KEY_MISSING" and result["ready"] is False


def _raises(exc):
    def list_models(**_kw):
        raise exc
    return list_models


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": FAKE_KEY})
    return httpx.HTTPStatusError(f"{code} from api.anthropic.com", request=request,
                                 response=httpx.Response(code, request=request))


@pytest.mark.parametrize("exc, state, detail", [
    (_status_error(401), "KEY_INVALID", "HTTP 401"),
    (_status_error(429), "RATE_LIMITED", "HTTP 429"),
    (httpx.ConnectTimeout("timed out"), "NETWORK_BLOCKED", "ConnectTimeout"),
])
def test_a_failed_probe_names_the_real_reason_and_never_the_key(monkeypatch, exc, state, detail):
    monkeypatch.setattr(reader_transport, "list_models", _raises(exc))

    result = vision_reader.reader_status()

    assert result["state"] == state and result["ready"] is False
    assert result["detail"] == detail
    assert result["reason"] and result["fix"]
    _assert_no_secret(result)


def test_ready_is_cached_so_the_screen_calls_claude_at_most_once_a_minute(monkeypatch):
    calls = []

    def list_models(*, timeout=None):
        calls.append(timeout)
        return ["claude-sonnet-5"]

    monkeypatch.setattr(reader_transport, "list_models", list_models)

    first = vision_reader.reader_status(now=1000.0)
    second = vision_reader.reader_status(now=1030.0)
    third = vision_reader.reader_status(now=1000.0 + vision_reader.STATUS_TTL_S + 1)

    assert first["state"] == second["state"] == third["state"] == "READY"
    assert len(calls) == 2
    assert calls[0] == vision_reader.STATUS_TIMEOUT_S
    _assert_no_secret(first)


# ------------------------------------------- #830 / #501: the per-task switch

@pytest.mark.parametrize("provider_value, engine, available", [
    ("per_task", "claude", True),        # its own engine line says claude: Claude for this step only
    ("per_task", "CLAUDE ", True),
    ("per_task", "ollama", False),       # GEOMETRY_READER_ENABLED alone sends no image under per_task
    ("per_task", "", False),
    ("claude", "ollama", True),          # the whole lane: as it always was
    ("claude", "claude", True),
    ("ollama", "claude", False),         # the master switch refuses, whatever the step says
    ("", "claude", False),
])
def test_the_page_image_reader_has_its_own_engine_line(monkeypatch, provider_value, engine, available):
    """CLAUDE.md rule 1: under per_task, Claude only for a step whose OWN
    engine setting says claude. `GEOMETRY_READER_ENABLED` (on in this file's
    fixture) is not that line: its first job is a local code reader."""
    monkeypatch.setattr(settings, "reasoning_provider", provider_value)
    monkeypatch.setattr(settings, "vision_reader_engine", engine)
    assert settings.geometry_reader_enabled is True
    provider, why = vision_reader.provider()
    assert (provider is not None) is available
    if available:
        assert provider.name == "claude" and why is None
    else:
        assert why


def test_the_engine_line_ships_local():
    from app.config import Settings
    assert Settings.model_fields["vision_reader_engine"].default == "ollama"


def test_under_per_task_the_status_names_the_engine_line(monkeypatch):
    from app import reasoning_provider as rp
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(reader_transport, "list_models", lambda **_kw: ["claude-test"])
    monkeypatch.setattr(settings, "vision_reader_engine", "ollama")
    status = vision_reader.reader_status(force=True)
    assert status["state"] == "TASK_ENGINE_LOCAL" and "VISION_READER_ENGINE=claude" in status["fix"]
    monkeypatch.setattr(settings, "vision_reader_engine", "claude")
    assert vision_reader.reader_status(force=True)["state"] == "READY"
    assert rp.claude_available()[0] is False               # wording, applicability, chat: local
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert vision_reader.reader_status(force=True)["state"] == "PROVIDER_OFF"
