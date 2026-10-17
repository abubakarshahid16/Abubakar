"""#459 (audit B07): a Claude reply without a `usage` block is charged its
worst case, not USD 0.

WHAT WAS WRONG. `claude_spend.metered` settled a reservation with
`usage=answer.get("usage")`; when the reply had no usage block that was None,
`_entry` priced the empty dict at 0, and the reserved worst case was replaced
by nothing. A billed call disappeared from the USD 5 / USD 20 caps.

No network: every transport is a fake.
"""
from __future__ import annotations

import pytest

from app import claude_spend
from app.config import settings

MODEL = "claude-sonnet-5"
STEP = "b07-step"
BODY = {"model": MODEL, "max_tokens": 4000,
        "messages": [{"role": "user", "content": "x" * 900}]}


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)


def _send(reply):
    def send(url, *, headers, body, timeout):
        return reply
    return send


def _worst() -> float:
    import json
    chars = len(json.dumps(BODY["messages"], ensure_ascii=False)) + len(json.dumps("", ensure_ascii=False))
    return round(claude_spend.worst_case_usd(MODEL, chars, BODY["max_tokens"]), 6)


def _settled() -> dict:
    [entry] = [e for e in claude_spend.entries() if e.get("settles")]
    return entry


@pytest.mark.parametrize("reply", [
    {"model": MODEL, "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]},
    {"model": MODEL, "stop_reason": "end_turn", "content": [], "usage": None},
    {"model": MODEL, "stop_reason": "end_turn", "content": [], "usage": {}},
    "not even a dict",
])
def test_a_reply_without_usage_settles_at_its_worst_case(reply):
    claude_spend.metered(_send(reply), step=STEP)("https://api.anthropic.com/v1/messages",
                                                  headers={}, body=BODY, timeout=1.0)
    entry = _settled()
    assert entry["cost_usd"] == _worst() > 0
    assert entry["estimated"] is True
    assert claude_spend.spent(STEP) == entry["cost_usd"], "the step's spend dropped below the call's worst case"


def test_a_reply_with_usage_is_still_charged_what_it_used():
    """Guard the guard: charging the worst case for EVERY reply would also
    pass the test above and would exhaust the caps ~10x too early."""
    reply = {"model": MODEL, "stop_reason": "end_turn", "content": [],
             "usage": {"input_tokens": 300, "output_tokens": 20}}
    claude_spend.metered(_send(reply), step=STEP)("https://api.anthropic.com/v1/messages",
                                                  headers={}, body=BODY, timeout=1.0)
    entry = _settled()
    assert entry["cost_usd"] == round(claude_spend.cost_usd(MODEL, reply["usage"]), 6)
    assert entry["cost_usd"] < _worst() and not entry.get("estimated")


def test_an_explicit_estimate_is_kept():
    held = claude_spend.reserve(STEP, 0.5, model=MODEL)
    entry = claude_spend.settle(held, usage=None, finish_reason="stop", estimated_usd=0.2)
    assert entry["cost_usd"] == 0.2 and entry["estimated"] is True
