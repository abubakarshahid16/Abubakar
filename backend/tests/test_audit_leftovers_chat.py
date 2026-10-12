"""Leftover of the 2026-09-30 audit (chat): a turn whose FIRST Claude call
fails after it was sent - so it is charged - falls back to the existing
pipeline, and the answer the reader sees must include that charge. The
ledger counted it; the answer did not. Mutation M1611
(`scripts/mutations/audit_leftovers.py`). No network: the transport is a fake.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import claude_spend
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _on
from tests.test_chat_pr1_model_lane import _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")


def _failing_first_call(monkeypatch, calls: list):
    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        if len(calls) == 1:
            # Sent, then dropped before the final usage: charged its worst case.
            yield {"type": "message_start",
                   "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 900}}}
            raise ConnectionResetError("dropped")
        yield from _stream_events({"model": "claude-sonnet-5", "stop_reason": "end_turn",
                                   "content": [{"type": "text", "text": "Hello."}],
                                   "usage": {"input_tokens": 50, "output_tokens": 5}})

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))


def test_a_charged_first_call_that_falls_back_is_in_the_answers_cost(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _failing_first_call(monkeypatch, calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = client.post(f"/api/conversations/{convo}/ask", json={"question": "hi"}).json()
    ledger = claude_spend.entries()
    failed = [e for e in ledger if str(e.get("finish_reason", "")).startswith("failed:")]
    assert failed and failed[0]["cost_usd"] > 0, "positive control: the ledger charged it"
    assert body["cost_usd"] is not None
    assert body["cost_usd"] == pytest.approx(round(sum(e["cost_usd"] for e in ledger), 6))
    assert any("failed and was charged" in n for n in body["notices"])
