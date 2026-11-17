"""The local reader and a model that thinks although told not to (order 14 lane L, 17 Nov 2026).

Measured on a real 20B model: with `think: false` the engine still returned a `thinking` text, the thinking used the whole output
limit and the reply came back EMPTY with done_reason "length"; the engine called that `bad_shape` (42 of 51 items of one valve run).
Invented model names and texts only; a fake engine answers. No real model is loaded."""

from __future__ import annotations

import json

import pytest

from app import agent_claude
from app import agent_review_local as local_mod

A, B = "invented-a:20b", "invented-b:9b"
SHOWS = {
    A: {"details": {"family": "alpha"}, "model_info": {"alpha.context_length": 16384}},
    B: {"details": {"family": "beta"}, "model_info": {"beta.context_length": 16384}},
}
PARTS = {
    "system": [{"type": "text", "text": "You review an invented paper."}],
    "messages": [
        {
            "role": "user",
            "content": [{"type": "text", "text": "ITEM R-x: invented rule."}],
        }
    ],
}
GOOD = json.dumps(
    {"answers": [{"item_id": "R-x", "verdict": "Query", "reason_code": "other"}]}
)


def _reply(content: str, done: str, thinking: str | None = None) -> dict:
    msg = {"content": content}
    if thinking is not None:
        msg["thinking"] = thinking
    return {"model": A, "message": msg, "done_reason": done, "prompt_eval_count": 40}


class Engine:
    """A fake local engine that answers from a list, in order, and records each request's output limit."""

    def __init__(self, replies):
        self.replies, self.limits = list(replies), []

    def __call__(self, path, body, *, timeout):
        self.limits.append(body["options"]["num_predict"])
        return self.replies.pop(0)


def _eng(replies) -> tuple[local_mod.LocalEngine, Engine]:
    fake = Engine(replies)
    eng = local_mod.LocalEngine(
        A,
        B,
        post=fake,
        unload=lambda _m: True,
        show=SHOWS.get,
        window=16384,
        size_mb=lambda _m: None,
        memory_mb=lambda: None,
        chat_active=lambda: False,
    )
    return eng, fake


def test_an_empty_reply_stopped_at_its_limit_is_an_answer_cut_off_not_a_bad_shape():
    eng, _ = _eng([_reply("", "length", thinking="t" * 2500)])
    with pytest.raises(agent_claude.AgentBadReply) as caught:
        eng.call(A, PARTS, 680)
    assert (
        caught.value.code == "stop_max_tokens"
    )  # the runner retries a cut-off once with a larger limit


def test_an_empty_reply_that_ended_normally_is_still_a_bad_shape():
    eng, _ = _eng([_reply("   ", "stop")])
    with pytest.raises(agent_claude.AgentBadReply) as caught:
        eng.call(A, PARTS, 680)
    assert caught.value.code == "bad_shape"


def test_a_reader_that_thinks_although_told_not_to_gets_room_to_think_on_later_requests():
    eng, fake = _eng(
        [
            _reply("", "length", thinking="t" * 2500),
            _reply(GOOD, "stop", thinking="short"),
        ]
    )
    base = eng.first_tokens(1)
    assert (
        base == local_mod.FIRST_TOKENS_BASE + local_mod.FIRST_TOKENS_PER_ITEM
    )  # nothing seen yet: the limit as before
    with pytest.raises(agent_claude.AgentBadReply):
        eng.call(A, PARTS, base)
    assert eng.first_tokens(1) == base + local_mod.THINKING_ALLOWANCE
    assert (
        eng.second_tokens(1)
        == local_mod.SECOND_TOKENS_BASE + local_mod.SECOND_TOKENS_PER_ITEM
    )  # the other reader is unchanged
    got, usd = eng.call(A, PARTS, eng.first_tokens(1))
    assert (
        json.loads(got["content"][0]["text"])["answers"][0]["item_id"] == "R-x"
        and usd == 0.0
    )
    assert fake.limits == [base, base + local_mod.THINKING_ALLOWANCE]
    stats = eng.stats()
    assert (
        stats["local_thinking_replies_first"] == 2
        and stats["local_thinking_replies_second"] == 0
    )


def test_a_reader_that_does_not_think_keeps_the_old_limit_and_shape():
    eng, fake = _eng([_reply(GOOD, "stop"), _reply(GOOD, "stop", thinking="")])
    eng.call(A, PARTS, eng.first_tokens(1))
    eng.call(A, PARTS, eng.first_tokens(1))
    assert (
        fake.limits == [680, 680] and eng.stats()["local_thinking_replies_first"] == 0
    )
