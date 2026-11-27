# ruff: noqa: F811
"""The local reader and a model that thinks although told not to (order 14 lane L, 17 Nov 2026).

Measured on a real 20B model: with `think: false` the engine still returned a `thinking` text, the thinking used the whole output
limit and the reply came back EMPTY with done_reason "length"; the engine called that `bad_shape` (42 of 51 items of one valve run).
Invented model names and texts only; a fake engine answers. No real model is loaded."""

from __future__ import annotations

import collections
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


# ---------------------------------------------------------------- the whole run: the item that showed the thinking is planned again

from tests.test_agent_review_guards import run_review, w  # noqa: E402, F401
from tests.test_agent_review_job import lines_of  # noqa: E402
from tests.test_n1_local_ai_reviewer import A_NAME, local  # noqa: E402, F401

ROOM = (
    local_mod.FIRST_TOKENS_BASE
    + local_mod.FIRST_TOKENS_PER_ITEM
    + local_mod.THINKING_ALLOWANCE
)


def test_a_model_that_thinks_anyway_is_planned_again_and_every_item_is_answered(
    local, monkeypatch
):
    from app import agent_review_local_run as lr
    from app import model_transport

    real = local["ollama"]
    plans: list[
        tuple[str, int]
    ] = []  # (item, its excerpt budget) for every plan of an item's windows
    plan = lr.LocalRunMixin.local_windows

    def counted(self, item, full):
        out = plan(self, item, full)
        plans.append((str(item.get("item_id")), out[3]))
        return out

    def thinking_engine(path, body, *, timeout):
        if (
            body["model"] == A_NAME
            and "CONTEXT CHECK" not in body["messages"][0]["content"]
            and (body["options"]["num_predict"] < ROOM or len(plans) == 1)
        ):  # the thinking spends the whole limit (and the windows of the first plan are too full to answer): empty, at its limit
            real.bodies.append(body)
            return {
                "model": A_NAME,
                "message": {"content": "", "thinking": "t" * 3000},
                "done_reason": "length",
                "prompt_eval_count": 50,
            }
        got = real(path, body, timeout=timeout)
        if body["model"] == A_NAME:
            got["message"]["thinking"] = "short"
        return got

    monkeypatch.setattr(lr.LocalRunMixin, "local_windows", counted)
    monkeypatch.setattr(model_transport, "post_json_retrying", thinking_engine)
    got = lines_of(run_review())
    assert got
    for (
        iid,
        ln,
    ) in got.items():  # (R-colour has no answer in the invented table: "no_answer_for_item" is its own, expected)
        reason = ln["reason"].lower()
        for bad in (
            "cut off",
            "ai call failed",
            "not asked",
            "bad_shape",
            "stop_max_tokens",
            "not all of",
        ):
            assert bad not in reason, (iid, bad)
    assert {i for i, ln in got.items() if ln["word"] != "Query"} >= {"R-coat", "R-mark"}
    limits = [b["options"]["num_predict"] for b in real.bodies if b["model"] == A_NAME]
    assert (
        limits[0] < ROOM and ROOM in limits
    )  # cut at the old limit, then asked with room to think
    # the first item asked was planned for the old limit, then ONCE more for the new one (its excerpt budget shrinks by the allowance)
    first = plans[0][0]
    again = [b for i, b in plans if i == first]
    assert len(again) == 2 and again[0] - again[1] == local_mod.THINKING_ALLOWANCE
    assert all(
        n == 1
        for i, n in collections.Counter(i for i, _ in plans).items()
        if i != first
    )


# ---------------------------------------------------------------- the answer net and a tokenizer that counts a little more than the estimate


def test_a_count_a_little_over_the_estimate_is_kept_only_when_the_request_cannot_have_been_cut():
    cut = local_mod._cut_prompt
    text = "word " * 600  # lower bound 500
    # measured on a real request: the model counted 7,962 tokens where the estimate said 7,643 (+4%): it fits even at 1.25x
    assert cut(7962, 16384, text, 680, 7643) is None
    # beyond the spread: the estimate cannot be trusted, discarded as before
    assert cut(9600, 16384, text, 680, 7643) == "prompt longer than the estimate said"
    # within the spread, but a request that would NOT fit the window at the spread: it may have been cut, discarded as before
    assert cut(13800, 16384, text, 680, 13200) == "prompt longer than the estimate said"
    # the other nets are unchanged
    assert (
        cut(15700, 16384, text, 680, 15000)
        == "prompt reached the room the window leaves it"
    )
    assert cut(100, 16384, text, 680, 7643) == "prompt shorter than the request needs"
