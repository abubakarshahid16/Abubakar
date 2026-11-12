"""U5: the plan says the truth when the Claude lane would refuse every call. The spend ledger holds the last standing refusal (no
credit, usage limit reached); `claude_spend.standing_refusal` reads it and the plan carries it. Invented ledger lines only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import claude_spend
from app.config import settings

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    return tmp_path / "spend.jsonl"


def put(path, *entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def release(at, word):
    return {"at": at.isoformat(timespec="seconds"), "releases": "r1", "step": "x", "reason": f"unbilled:HTTPStatusError:http_400:{word}"}


def ok(at):
    return {"at": at.isoformat(timespec="seconds"), "step": "x", "model": "m", "input_tokens": 100, "output_tokens": 5, "cost_usd": 0.01, "finish_reason": "end_turn"}


def test_a_usage_limit_answer_is_a_closed_word_and_never_stores_the_message():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = httpx.HTTPStatusError("400", request=req, response=httpx.Response(
        400, request=req, json={"error": {"type": "invalid_request_error", "message": "You have reached your specified API usage limits. SECRET-ECHO"}}))
    assert claude_spend.failure_word(err) == "HTTPStatusError:http_400:usage_limit"
    assert claude_spend.failure_words(err) == claude_spend.USAGE_LIMIT_WORDS
    assert "SECRET" not in claude_spend.failure_word(err)


def test_the_newest_standing_refusal_is_read_back_with_its_time(ledger):
    put(ledger, release(NOW - timedelta(minutes=30), "no_credit"), release(NOW - timedelta(minutes=10), "usage_limit"))
    got = claude_spend.standing_refusal(NOW)
    assert got["cause"] == "usage_limit" and got["words"] == claude_spend.USAGE_LIMIT_WORDS and got["at"].startswith("2026-11-12T14:50")


def test_a_call_that_went_through_since_clears_it_and_an_old_one_expires(ledger):
    put(ledger, release(NOW - timedelta(minutes=30), "usage_limit"), ok(NOW - timedelta(minutes=5)))
    assert claude_spend.standing_refusal(NOW) is None
    put(ledger, release(NOW - timedelta(hours=claude_spend.STANDING_REFUSAL_HOURS + 1), "usage_limit"))
    assert claude_spend.standing_refusal(NOW) is None


def test_an_ordinary_failure_or_an_empty_ledger_is_no_standing_refusal(ledger):
    assert claude_spend.standing_refusal(NOW) is None
    put(ledger, {"at": NOW.isoformat(), "releases": "r", "step": "x", "reason": "unbilled:ReadTimeout"})
    assert claude_spend.standing_refusal(NOW) is None


def test_the_plan_carries_the_standing_refusal(monkeypatch):
    from app import review_engine

    monkeypatch.setattr(claude_spend, "standing_refusal", lambda *a, **k: {"cause": "usage_limit", "words": claude_spend.USAGE_LIMIT_WORDS, "at": "2026-11-12T14:50:00+00:00"})
    from tests.test_b1_review_engine import open_facts

    monkeypatch.setattr(review_engine, "read_facts", lambda *a, **k: (open_facts(), None))
    monkeypatch.setattr(review_engine, "_earlier_books", lambda *a, **k: [])
    monkeypatch.setattr(review_engine, "_last_cost", lambda *a, **k: None)
    got = review_engine.plan_for(None, "doc", frozenset(), "automatic")
    assert got["claude_standing_refusal"]["words"] == claude_spend.USAGE_LIMIT_WORDS
