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
def _declared():
    from app import claude_approved

    ac.reset_shared_meter_for_tests()
    with claude_approved.carrying(["doc-1"]):
        yield
    ac.reset_shared_meter_for_tests()


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
        "temperature" not in s.bodies[0] and s.bodies[0]["model"] == "claude-sonnet-5-5"
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
    out = ac._second_opinion(F, EV, meter=ac.SpendMeter(), send=s, env=ENV)
    assert out["agree"] is True and out["usd"] > 0
    assert s.bodies[0]["model"] == "claude-opus-5-5"
    assert "dq" in s.bodies[0]["messages"][0]["content"][0]["text"]
    assert s.bodies[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert (
        ac._second_opinion(
            F,
            EV,
            meter=ac.SpendMeter(),
            send=op('{"agree": false, "reason": "x"}'),
            env=ENV,
        )["agree"]
        is False
    )


@pytest.mark.parametrize(
    "text", ["maybe", '{"agree": "yes"}', '{"agree": 1}', '{"reason": "r"}', "{broken"]
)
def test_second_opinion_garbage_is_none(text):
    assert (
        ac._second_opinion(F, EV, meter=ac.SpendMeter(), send=op(text), env=ENV)[
            "agree"
        ]
        is None
    )


def test_second_opinion_reason_is_capped_and_failures_are_none():
    long = op(json.dumps({"agree": True, "reason": "w " * 50}))
    assert (
        len(
            ac._second_opinion(F, EV, meter=ac.SpendMeter(), send=long, env=ENV)[
                "reason"
            ].split()
        )
        <= 20
    )
    assert (
        ac._second_opinion(
            F, EV, meter=ac.SpendMeter(), send=op('{"agree": true}'), env={}
        )["agree"]
        is None
    )
    assert (
        ac._second_opinion(
            F,
            EV,
            meter=ac.SpendMeter(),
            send=op('{"agree": true}'),
            env=ENV,
            model=ac.LEAD_MODEL,
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


def test_temperature_absent_for_a_model_that_rejects_it_and_present_for_one_that_accepts():
    assert claude_spend
    s = Sender(tool_use(doc="D", page=1))
    provider(s).complete(MSGS, SPECS)  # claude-sonnet-5-5 rejects temperature
    assert "temperature" not in s.bodies[0]
    s2 = Sender(tool_use(doc="D", page=1))
    provider(s2, model="claude-haiku-4-5").complete(MSGS, SPECS)
    assert s2.bodies[0]["temperature"] == 0
    s3 = op('{"agree": true}')
    ac._second_opinion(F, EV, meter=ac.SpendMeter(), send=s3, env=ENV)
    assert "temperature" not in s3.bodies[0]


def test_total_cap_stops_before_sending_the_over_cap_call():
    s = Sender(tool_use(doc="D", page=1))
    p = provider(s, total_cap_usd=0.05)
    p.complete(MSGS, SPECS)
    first = p.spent
    assert first > 0
    worst = claude_spend.worst_case_usd(ac.LEAD_MODEL, 300, ac.MAX_TOKENS)
    p.meter.cap = first + worst * 0.5
    n = len(s.bodies)
    with pytest.raises(ac.AgentBudgetStop):
        p.complete(MSGS, SPECS)
    assert len(s.bodies) == n and p.spent == first


def test_second_opinions_count_toward_the_same_cap():
    p = provider(Sender(tool_use(doc="D", page=1)))
    out = p.second_opinion(F, EV, send=op('{"agree": true, "reason": "ok"}'))
    assert (
        out["agree"] is True and out["usd"] > 0 and p.spent == pytest.approx(out["usd"])
    )
    p.meter.cap = p.spent
    blocked = op('{"agree": true}')
    assert p.second_opinion(F, EV, send=blocked)["agree"] is None
    assert blocked.bodies == []


def test_model_reasons_are_capped_in_tool_turns_and_finals():
    long = "w " * 80
    t = provider(Sender(tool_use(doc="D", page=1, reason=long))).complete(MSGS, SPECS)
    assert len(t["reason"].split()) <= 20 and len(t["reason"]) <= 160
    f = provider(
        Sender(
            [{"type": "text", "text": json.dumps({"color": "YELLOW", "reason": long})}],
            stop="end_turn",
        )
    ).complete(MSGS, SPECS)["final"]
    assert len(f["reason"].split()) <= 20 and len(f["reason"]) <= 160
    longword = provider(Sender(tool_use(doc="D", page=1, reason="x" * 500))).complete(
        MSGS, SPECS
    )
    assert len(longword["reason"]) <= 160


def test_no_declared_documents_is_refused_and_nothing_is_sent(monkeypatch):
    from app import claude_approved

    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    s = Sender(tool_use(doc="D", page=1))
    token = claude_approved._CARRIED.set(None)
    try:
        with pytest.raises(ac.AgentGateClosed) as e:
            provider(s).complete(MSGS, SPECS)
    finally:
        claude_approved._CARRIED.reset(token)
    assert s.bodies == [] and e.value.code == "undeclared_documents"


def test_empty_declaration_is_refused_and_nothing_is_sent():
    from app import claude_approved

    s = Sender(tool_use(doc="D", page=1))
    with claude_approved.per_request_consent([]):
        with pytest.raises(ac.AgentGateClosed) as e:
            provider(s).complete(MSGS, SPECS)
    assert s.bodies == [] and e.value.code == "undeclared_documents"


def test_a_failed_send_and_a_non_dict_reply_are_charged_at_worst_case():
    p = provider(Sender([], raises=TimeoutError("t")))
    with pytest.raises(ac.AgentTransportError):
        p.complete(MSGS, SPECS)
    assert p.spent > 0
    s = Sender([])
    s.reply = "not a dict"
    q = provider(s, total_cap_usd=5.0)
    with pytest.raises(ac.AgentBadReply):
        q.complete(MSGS, SPECS)
    assert q.spent > 0


def test_a_provably_unbilled_failure_is_not_charged():
    from app import reader_transport

    p = provider(Sender([], raises=reader_transport.TransportRefused("no", sent=False)))
    with pytest.raises(ac.AgentTransportError):
        p.complete(MSGS, SPECS)
    assert p.spent == 0.0


def test_providers_share_one_process_wide_meter():
    a, b = (
        provider(Sender(tool_use(doc="D", page=1))),
        provider(Sender(tool_use(doc="D", page=1))),
    )
    a.complete(MSGS, SPECS)
    assert b.spent == a.spent > 0
    b.complete(MSGS, SPECS)
    assert a.spent == b.spent


def test_the_estimate_counts_the_tools_sent():
    big = [
        {
            "name": "open_page",
            "description": "d" * 300_000,
            "input_schema": {"type": "object"},
        }
    ]
    s = Sender(tool_use(doc="D", page=1))
    p = provider(s, total_cap_usd=0.1)
    p.complete(MSGS, SPECS)  # small tools fit under the cap
    with pytest.raises(ac.AgentBudgetStop):
        p.complete(MSGS, big)
    assert len(s.bodies) == 1


def test_the_bare_second_opinion_is_not_public():
    assert not hasattr(ac, "second_opinion")


def test_the_answering_model_comes_from_the_response_not_the_config():
    s = Sender(tool_use(doc="D", page=1))
    s.reply["model"] = "claude-sonnet-5-5-20261001"
    assert provider(s).complete(MSGS, SPECS)["model"] == "claude-sonnet-5-5-20261001"
    del s.reply["model"]
    assert provider(s).complete(MSGS, SPECS)["model"] == "unknown"
    o = op('{"agree": true, "reason": "ok"}')
    o.reply["model"] = "claude-opus-5-5-20261001"
    assert (
        provider(s).second_opinion(F, EV, send=o)["model"] == "claude-opus-5-5-20261001"
    )
    del o.reply["model"]
    assert provider(s).second_opinion(F, EV, send=o)["model"] == "unknown"


def test_budget_and_gate_stops_are_fatal_and_bad_replies_are_not():
    assert ac.AgentBudgetStop.fatal and ac.AgentGateClosed.fatal
    assert not ac.AgentBadReply.fatal and not ac.AgentTransportError.fatal


# ---- the key: process env first, then the app settings; switches process env only; never printed


SENTINEL = "sk-ant-api03-Zq7Xv9Lm2Bn4Cr8Tw3Kd6Hf1Jg5Ps0Ye"
NO_KEY = {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"}


class Headers(Sender):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.headers = []

    def __call__(self, url, *, headers, body, timeout):
        self.headers.append(dict(headers))
        return super().__call__(url, headers=headers, body=body, timeout=timeout)


def test_env_key_wins_over_settings(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "settings-key-value")
    s = Headers(tool_use(doc="D", page=1))
    ac.ClaudeProvider(
        send=s, env={**ENV, "ANTHROPIC_API_KEY": "env-key-value"}
    ).complete(MSGS, SPECS)
    assert s.headers[0]["x-api-key"] == "env-key-value"


def test_settings_key_is_the_fallback_when_env_has_none(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "settings-key-value")
    s = Headers(tool_use(doc="D", page=1))
    ac.ClaudeProvider(send=s, env=NO_KEY).complete(MSGS, SPECS)
    assert s.headers[0]["x-api-key"] == "settings-key-value"


def test_no_key_anywhere_is_gate_closed_and_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentGateClosed) as e:
        ac.ClaudeProvider(send=s, env=NO_KEY).complete(MSGS, SPECS)
    assert s.bodies == [] and e.value.code == "no_key_in_env_or_settings"


def test_a_broken_settings_fallback_is_a_code_only_gate_closed(monkeypatch):
    from app import reader_api

    def boom(_env):
        raise ValueError(SENTINEL)

    monkeypatch.setattr(reader_api, "_sources", boom)
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentGateClosed) as e:
        ac.ClaudeProvider(send=s, env=NO_KEY).complete(MSGS, SPECS)
    assert s.bodies == [] and e.value.code == "settings_unreadable"
    assert SENTINEL not in str(e.value) + repr(e.value) and e.value.__cause__ is None


@pytest.mark.parametrize(
    "drop",
    [
        "REASONING_PROVIDER",
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
    ],
)
def test_flags_stay_process_env_only_even_when_settings_holds_a_key(monkeypatch, drop):
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentGateClosed):
        ac.ClaudeProvider(
            send=s, env={k: v for k, v in ENV.items() if k != drop}
        ).complete(MSGS, SPECS)
    assert s.bodies == []


def test_the_key_is_never_stored_on_the_provider(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    p = ac.ClaudeProvider(send=Headers(tool_use(doc="D", page=1)), env=NO_KEY)
    p.complete(MSGS, SPECS)
    assert (
        SENTINEL not in repr(vars(p))
        and SENTINEL not in repr(vars(ac))
        and SENTINEL not in repr(NO_KEY)
    )


def _leaks(*texts):
    return [t for t in texts if SENTINEL in t or SENTINEL[:8] in t]


def test_the_key_appears_nowhere_but_the_request_headers(
    monkeypatch, caplog, capfd, tmp_path
):
    import logging

    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    env = {**ENV, "ANTHROPIC_API_KEY": SENTINEL}
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []
    ok = Headers(tool_use(doc="D", page=1))
    seen.append(repr(ac.ClaudeProvider(send=ok, env=env).complete(MSGS, SPECS)))
    assert ok.headers[0]["x-api-key"] == SENTINEL  # the one allowed place
    seen.append(
        repr(ac.ClaudeProvider(send=Headers([]), env=env).second_opinion(F, EV))
    )
    for sender, e in (
        (Headers([], raises=RuntimeError(SENTINEL[:3])), env),  # a failing call
        (
            Headers([{"type": "text", "text": "nope"}], stop="end_turn"),
            env,
        ),  # garbage reply
        (
            Headers(tool_use(doc="D", page=1)),
            NO_KEY,
        ),  # gate closed (no key anywhere after the next line)
    ):
        if e is NO_KEY:
            monkeypatch.setattr(settings, "anthropic_api_key", "")
            e = {k: v for k, v in e.items() if k != "REASONING_PROVIDER"}
        with pytest.raises(ac.AgentClaudeError) as err:
            ac.ClaudeProvider(send=sender, env=e).complete(MSGS, SPECS)
        seen += [str(err.value), repr(err.value)]
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    with pytest.raises(ac.AgentBudgetStop) as err:
        ac.ClaudeProvider(send=Headers(tool_use(doc="D", page=1)), env=env).complete(
            MSGS, SPECS
        )
    seen += [str(err.value), repr(err.value)]
    ledger = (
        settings.claude_spend_log.read_text()
        if settings.claude_spend_log.exists()
        else ""
    )
    err_out = capfd.readouterr()
    assert _leaks(caplog.text, ledger, err_out.out, err_out.err, *seen) == []


def _set_process_env(monkeypatch, **extra):
    for k, v in {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


@pytest.mark.parametrize("env_key", [None, "env-key-value"])
def test_the_process_environment_is_never_written(monkeypatch, env_key):
    import os

    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    _set_process_env(monkeypatch, **({"ANTHROPIC_API_KEY": env_key} if env_key else {}))
    before = dict(os.environ)
    ac.ClaudeProvider(send=Headers(tool_use(doc="D", page=1))).complete(MSGS, SPECS)
    assert dict(os.environ) == before and (
        env_key or "ANTHROPIC_API_KEY" not in os.environ
    )


@pytest.mark.parametrize("blank", ["   ", "\t\n", " \n\t "])
def test_a_blank_env_key_falls_through_to_settings(monkeypatch, blank):
    monkeypatch.setattr(settings, "anthropic_api_key", "settings-key-value")
    s = Headers(tool_use(doc="D", page=1))
    ac.ClaudeProvider(send=s, env={**ENV, "ANTHROPIC_API_KEY": blank}).complete(
        MSGS, SPECS
    )
    assert s.headers[0]["x-api-key"] == "settings-key-value"


def test_settings_reasoning_provider_never_opens_the_gate(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentGateClosed):
        ac.ClaudeProvider(
            send=s, env={k: v for k, v in ENV.items() if k != "REASONING_PROVIDER"}
        ).complete(MSGS, SPECS)
    assert s.bodies == [] and ac.gate_open({}) is False


def _chain(exc):
    seen = []
    while exc is not None and exc not in seen:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


def _holds_key(exc) -> bool:
    for e in _chain(exc):
        if SENTINEL in repr(e.args):
            return True
        tb = e.__traceback__
        while tb is not None:
            if SENTINEL in repr(tb.tb_frame.f_locals):
                return True
            tb = tb.tb_next
    return False


@pytest.mark.parametrize(
    "sender",
    [
        lambda: Headers([], raises=RuntimeError("boom")),
        lambda: Headers([{"type": "text", "text": "x"}], stop="max_tokens"),
    ],
)
def test_no_raised_error_chain_or_frame_holds_the_key(monkeypatch, sender):
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    with pytest.raises(ac.AgentClaudeError) as e:
        ac.ClaudeProvider(send=sender(), env=NO_KEY).complete(MSGS, SPECS)
    assert not _holds_key(e.value)
    assert e.value.__context__ is None and e.value.__cause__ is None


def test_gate_and_settings_errors_hold_no_key_in_any_frame(monkeypatch):
    from app import reader_api

    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    with pytest.raises(ac.AgentGateClosed) as e:  # flag refused inside build_request
        ac.ClaudeProvider(
            send=Sender([]),
            env={k: v for k, v in NO_KEY.items() if k != "STANDARDS_READER_ENABLED"},
        ).complete(MSGS, SPECS)
    assert not _holds_key(e.value) and e.value.__context__ is None

    def boom(_env):
        raise ValueError(SENTINEL)

    monkeypatch.setattr(reader_api, "_sources", boom)
    with pytest.raises(ac.AgentGateClosed) as e2:
        ac.ClaudeProvider(send=Sender([]), env=NO_KEY).complete(MSGS, SPECS)
    assert e2.value.__context__ is None and not _holds_key(e2.value)


def test_undeclared_documents_error_holds_no_key_in_any_frame(monkeypatch):
    from app import claude_approved

    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    for env in (NO_KEY, {**ENV, "ANTHROPIC_API_KEY": SENTINEL}):
        token = claude_approved._CARRIED.set(frozenset())
        try:
            with pytest.raises(ac.AgentGateClosed) as e:
                ac.ClaudeProvider(send=Sender([]), env=env).complete(MSGS, SPECS)
        finally:
            claude_approved._CARRIED.reset(token)
        assert e.value.code == "undeclared_documents"
        walk = _frame_locals(e.value)
        # the injected env of the second case is the caller's own dict; the adapter adds no copy of it
        assert not any(SENTINEL in v for name, v in walk if name != "env")


def test_over_cap_error_holds_no_key_in_any_frame(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SENTINEL)
    s = Sender(tool_use(doc="D", page=1))
    with pytest.raises(ac.AgentBudgetStop) as e:
        ac.ClaudeProvider(send=s, env=NO_KEY, total_cap_usd=0.0).complete(MSGS, SPECS)
    assert s.bodies == [] and e.value.code == "test_cap"
    assert not _holds_key(e.value)


def _frame_locals(exc):
    out = []
    tb = exc.__traceback__
    while tb is not None:
        out += [(k, repr(v)) for k, v in tb.tb_frame.f_locals.items()]
        tb = tb.tb_next
    return out
