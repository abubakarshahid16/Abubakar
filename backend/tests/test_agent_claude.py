"""agent_claude (#1690): the Claude provider for the agent proof test. Fake senders only: no network, no key."""

from __future__ import annotations

import json

import pytest

from app import agent_claude as ac
from app import claude_spend
from app.config import settings

ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "test-key-not-real",
}
SPECS = [
    {"name": "open_page", "description": "d", "params": {"doc": "id", "page": "n"}},
    {
        "name": "ask_engineer",
        "description": "d",
        "input_schema": {"type": "object", "properties": {"item": {"type": "string"}}},
    },
]
USAGE = {
    "input_tokens": 1000,
    "output_tokens": 100,
    "cache_creation_input_tokens": 2000,
    "cache_read_input_tokens": 4000,
}


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)


class Sender:
    def __init__(self, content, usage=USAGE, stop="tool_use", raises=None):
        self.reply = {
            "model": ac.LEAD_MODEL,
            "stop_reason": stop,
            "content": content,
            "usage": usage,
        }
        self.bodies, self.raises = [], raises

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(body)
        if self.raises:
            raise self.raises
        return self.reply


MSGS = [{"role": "user", "content": {"item": {"id": "i1"}, "instruction": "go"}}]


def provider(sender, **kw):
    return ac.ClaudeProvider(send=sender, env=ENV, **kw)


def tool_use(name="open_page", **inp):
    return [{"type": "tool_use", "id": "t1", "name": name, "input": inp}]


def test_tool_use_is_parsed_with_reason_split_out():
    s = Sender(tool_use(doc="D1", page=3, reason="need the page " + "x " * 30))
    out = provider(s).complete(MSGS, SPECS)
    assert out["tool"] == "open_page" and out["args"] == {"doc": "D1", "page": 3}
    assert len(out["reason"].split()) <= 20
    assert s.bodies[0]["tools"][0]["input_schema"]["properties"]["reason"]
    assert s.bodies[0]["tool_choice"]["disable_parallel_tool_use"] is True
    assert (
        s.bodies[0]["temperature"] == 0 and s.bodies[0]["model"] == "claude-sonnet-5-5"
    )


def test_only_the_first_tool_call_is_used():
    content = tool_use(doc="A", page=1) + tool_use("ask_engineer", item="z")
    assert provider(Sender(content)).complete(MSGS, SPECS)["args"]["doc"] == "A"


def test_final_text_is_parsed_fenced_or_bare():
    for text in (
        '{"color": "YELLOW", "reason": "r"}',
        'ok\n```json\n{"color": "RED"}\n```',
    ):
        out = provider(
            Sender([{"type": "text", "text": text}], stop="end_turn")
        ).complete(MSGS, SPECS)
        assert out["final"]["color"] in ("YELLOW", "RED") and "tool" not in out


@pytest.mark.parametrize(
    "content,stop",
    [
        ([{"type": "text", "text": "I think it is fine."}], "end_turn"),
        ([], "end_turn"),
        (tool_use("delete_everything", x=1), "tool_use"),
        (
            [{"type": "tool_use", "id": "t", "name": "open_page", "input": "oops"}],
            "tool_use",
        ),
        ([{"type": "text", "text": '{"color": "GREEN"}'}], "refusal"),
        ([{"type": "text", "text": '{"color": "GREEN"}'}], "max_tokens"),
    ],
)
def test_garbage_reply_is_an_error_not_a_crash(content, stop):
    with pytest.raises(ac.AgentBadReply):
        provider(Sender(content, stop=stop)).complete(MSGS, SPECS)


def test_non_dict_reply_is_an_error():
    s = Sender([])
    s.reply = "not a dict"
    with pytest.raises(ac.AgentBadReply):
        provider(s).complete(MSGS, SPECS)


def test_cache_control_on_system_and_first_user_block_every_call():
    msgs = [
        *MSGS,
        {
            "role": "assistant",
            "content": {
                "tool": "open_page",
                "args": {"doc": "D", "page": 1},
                "reason": "r",
            },
        },
        {"role": "tool", "name": "open_page", "content": {"ok": True}},
    ]
    s = Sender(tool_use(doc="D", page=2))
    p = provider(s, system="skill text")
    p.complete(MSGS, SPECS)
    p.complete(msgs, SPECS)
    for body in s.bodies:
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "skill text" in body["system"][0]["text"]
        assert body["messages"][0]["content"][-1]["cache_control"] == {
            "type": "ephemeral"
        }
    later = s.bodies[1]["messages"]
    assert later[1]["content"][0]["type"] == "tool_use"
    assert later[2]["content"][0]["tool_use_id"] == later[1]["content"][0]["id"]
    assert "cache_control" not in later[2]["content"][0]


def test_usd_comes_from_usage_including_cache_read_and_write():
    out = provider(Sender(tool_use(doc="D", page=1))).complete(MSGS, SPECS)
    p_in, p_out, p_write, p_read = claude_spend.price_for(ac.LEAD_MODEL)
    want = (1000 * p_in + 100 * p_out + 2000 * p_write + 4000 * p_read) / 1_000_000
    assert out["usd"] == pytest.approx(want) and want > 0
    cheaper = provider(
        Sender(tool_use(doc="D", page=1), usage={**USAGE, "cache_read_input_tokens": 0})
    )
    assert cheaper.complete(MSGS, SPECS)["usd"] < out["usd"]


def test_every_call_is_metered_in_the_ledger():
    provider(Sender(tool_use(doc="D", page=1))).complete(MSGS, SPECS)
    assert claude_spend.spent(ac.STEP) > 0


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "REASONING_PROVIDER": "local"},
        {k: v for k, v in ENV.items() if k != "STANDARDS_READER_ALLOW_PUBLIC_EGRESS"},
        {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"},
    ],
)
def test_gate_closed_is_an_error_and_nothing_is_sent(env):
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentGateClosed):
        ac.ClaudeProvider(send=s, env=env).complete(MSGS, SPECS)
    assert s.bodies == []


def test_budget_exceeded_is_an_error_and_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentBudgetStop):
        provider(s).complete(MSGS, SPECS)
    assert s.bodies == []


def test_error_messages_carry_codes_only():
    secret = "SECRET-DOCUMENT-TEXT"
    s = Sender([], raises=RuntimeError(secret))
    with pytest.raises(ac.AgentTransportError) as e:
        provider(s).complete(MSGS, SPECS)
    assert (
        secret not in str(e.value)
        and secret not in repr(e.value)
        and e.value.__cause__ is None
    )
    with pytest.raises(ac.AgentBadReply) as e2:
        provider(Sender([{"type": "text", "text": secret}], stop="end_turn")).complete(
            MSGS, SPECS
        )
    assert secret not in str(e2.value)


def op(text, **kw):
    return Sender([{"type": "text", "text": text}], stop="end_turn", **kw)


F = {"color": "GREEN"}
EV = {"doc_quote": "dq", "clause_quote": "cq"}


def test_second_opinion_agree_and_disagree():
    s = op('{"agree": true, "reason": "quotes match"}')
    out = ac.second_opinion(F, EV, send=s, env=ENV)
    assert out["agree"] is True and out["usd"] > 0
    assert s.bodies[0]["model"] == "claude-opus-5-5"
    assert "dq" in s.bodies[0]["messages"][0]["content"][0]["text"]
    assert s.bodies[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert (
        ac.second_opinion(F, EV, send=op('{"agree": false, "reason": "x"}'), env=ENV)[
            "agree"
        ]
        is False
    )


@pytest.mark.parametrize(
    "text", ["maybe", '{"agree": "yes"}', '{"agree": 1}', '{"reason": "r"}', "{broken"]
)
def test_second_opinion_garbage_is_none(text):
    assert ac.second_opinion(F, EV, send=op(text), env=ENV)["agree"] is None


def test_second_opinion_reason_is_capped_and_failures_are_none():
    long = op(json.dumps({"agree": True, "reason": "w " * 50}))
    assert len(ac.second_opinion(F, EV, send=long, env=ENV)["reason"].split()) <= 20
    assert ac.second_opinion(F, EV, send=op('{"agree": true}'), env={})["agree"] is None
    assert (
        ac.second_opinion(
            F, EV, send=op('{"agree": true}'), env=ENV, model=ac.LEAD_MODEL
        )["agree"]
        is None
    )


def test_project_cost():
    out = ac.project_cost(5, 50, 1.0, 0.5)
    assert out["per_item"] == pytest.approx(0.2)
    assert out["projected_total"] == pytest.approx(1.0 + 45 * 0.2 * 1.5)
    assert ac.project_cost(50, 50, 10.0, 0.5)["projected_total"] == pytest.approx(10.0)
    assert ac.project_cost(0, 50, 0.0, 0.5)["projected_total"] is None
    assert ac.project_cost(6, 5, 1.0, 0.0)["projected_total"] is None
