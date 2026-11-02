"""#458 (audit F06): a Claude answer that fails its JSON schema is not cached.

WHAT WAS WRONG. `ClaudeProvider._answered` cached every reply that ended with
`stop`, valid or not. A reply that broke the packet's schema was then served
from the cache on every repeat of the same packet - free, instantly, and wrong
every time - so a retry could never get a different answer. An entry already
on disk from before the fix is now a miss, not a hit.

No network: the transport is a fake that counts its calls.
"""
from __future__ import annotations

import json

import pytest

from app import claude_answer_cache, claude_spend
from app import reasoning_provider as rp
from app.config import settings
from tests.test_chat import temp_storage  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import KEY

pytestmark = pytest.mark.usefixtures("temp_storage")

MODEL = "claude-sonnet-5"
SCHEMA = {"type": "object", "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}


@pytest.fixture(autouse=True)
def _env(temp_storage, tmp_path, monkeypatch):  # noqa: F811 - temp_storage first: it moves data_dir
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / tmp_path.name)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _packet():
    return rp.Packet(prompt="Is it?", num_ctx=4096, num_predict=200, step="f06",
                     json_schema=SCHEMA)


def _counting(reply_text: str):
    calls = []

    def send(url, *, headers, body, timeout):
        calls.append(1)
        return {"model": MODEL, "stop_reason": "end_turn",
                "content": [{"type": "text", "text": reply_text}],
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    return send, calls


def test_an_answer_that_fails_its_schema_is_not_cached():
    send, calls = _counting("not json at all")
    provider = rp.ClaudeProvider(MODEL, transport=send)
    first = provider.reason(_packet())
    assert first.schema_errors, "the fake reply should fail the schema"
    second = provider.reason(_packet())
    assert len(calls) == 2, "the invalid answer was served from the cache on the repeat"
    assert second.finish_reason == "stop" and second.schema_errors
    assert not list((settings.claude_cache_dir).rglob("*.json"))


def test_a_valid_answer_is_still_cached():
    """Guard the guard: refusing to cache EVERYTHING would also pass the test
    above, and would cost a paid call on every repeat."""
    send, calls = _counting('{"answer": "yes"}')
    provider = rp.ClaudeProvider(MODEL, transport=send)
    provider.reason(_packet())
    second = provider.reason(_packet())
    assert len(calls) == 1 and second.cost_usd == 0.0 and second.schema_errors == ()
    assert [e["finish_reason"] for e in claude_spend.entries()][-1] == "cache_hit"


def test_a_bad_answer_cached_before_the_fix_is_a_miss():
    packet = _packet()
    body = rp.ClaudeProvider(MODEL)._request(packet)[1]
    key = claude_answer_cache.key_of(packet.step, packet.prompt_version, body)
    claude_answer_cache.write(
        key,
        step=packet.step,
        cost_usd=0.1,
        payload={
            "model": MODEL,
            "stop_reason": "end_turn",
            "usage": {},
            "content": [{"type": "text", "text": "not json at all"}],
        },
    )
    send, calls = _counting('{"answer": "yes"}')
    answer = rp.ClaudeProvider(MODEL, transport=send).reason(packet)
    assert len(calls) == 1, "the stale invalid entry was served instead of asking again"
    assert answer.schema_errors == () and json.loads(answer.text) == {"answer": "yes"}
