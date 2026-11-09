"""agent_local_lead (#1690): the local lead provider. A fake transport only: no Ollama, no model, no network."""

from __future__ import annotations

import json
import logging

import pytest

from app import agent_local_lead as al
from app import model_memory, model_transport

SPECS = [
    {"name": "open_page", "description": "d", "params": {"doc": "id", "page": "n"}},
    {
        "name": "ask_engineer",
        "description": "d",
        "input_schema": {"type": "object", "properties": {"item": {"type": "string"}}},
    },
]
MSGS = [{"role": "user", "content": {"item": {"id": "i1"}, "instruction": "go"}}]
SENTINEL = "SECRET-DOCUMENT-TEXT-91f3"


class Fake:
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises, self.bodies = reply, raises, []

    def __call__(self, path, body, *, timeout):
        assert path == "/api/chat"
        self.bodies.append((body, timeout))
        if self.raises:
            raise self.raises
        return self.reply


def msg(content="", calls=None, **extra):
    m = {"role": "assistant", "content": content}
    if calls is not None:
        m["tool_calls"] = calls
    return {"model": "qwen-test:35b", "message": m, **extra}


def call(name="open_page", args=None):
    return [
        {
            "function": {
                "name": name,
                "arguments": {"doc": "D1", "page": 3} if args is None else args,
            }
        }
    ]


@pytest.fixture
def fake(monkeypatch):
    def install(reply=None, raises=None):
        f = Fake(reply, raises)
        monkeypatch.setattr(model_transport, "post_json_retrying", f)
        return f

    return install


def test_tool_call_with_dict_args_and_reason_split_out(fake):
    f = fake(
        msg(
            calls=call(
                args={"doc": "D1", "page": 3, "reason": "need the page " + "x " * 30}
            )
        )
    )
    out = al.LocalProvider().complete(MSGS, SPECS)
    assert out["tool"] == "open_page" and out["args"] == {"doc": "D1", "page": 3}
    assert (
        len(out["reason"].split()) <= 20
        and out["usd"] == 0.0
        and out["model"] == "qwen-test:35b"
    )
    body, _t = f.bodies[0]
    assert (
        body["tools"][0]["type"] == "function"
        and body["tools"][0]["function"]["name"] == "open_page"
    )
    assert "reason" in body["tools"][0]["function"]["parameters"]["properties"]


def test_tool_call_with_string_args(fake):
    fake(msg(calls=call(args=json.dumps({"doc": "D2", "page": 1}))))
    assert al.LocalProvider().complete(MSGS, SPECS)["args"] == {"doc": "D2", "page": 1}


def test_only_the_first_tool_call_is_used(fake):
    fake(msg(calls=call(args={"doc": "A"}) + call("ask_engineer", {"item": "z"})))
    assert al.LocalProvider().complete(MSGS, SPECS)["args"] == {"doc": "A"}


@pytest.mark.parametrize(
    "calls",
    [
        call("delete_all"),
        call(args="not json"),
        call(args="[1]"),
        [{"function": "x"}],
        ["x"],
    ],
)
def test_a_bad_tool_call_is_a_bad_reply(fake, calls):
    fake(msg(calls=calls))
    with pytest.raises(al.LocalBadReply):
        al.LocalProvider().complete(MSGS, SPECS)


def test_final_json_is_parsed_and_reason_capped(fake):
    fake(msg('{"color": "YELLOW", "reason": "' + "w " * 40 + '"}'))
    out = al.LocalProvider().complete(MSGS, SPECS)
    assert (
        out["final"]["color"] == "YELLOW"
        and len(out["final"]["reason"].split()) <= 20
        and "tool" not in out
    )


@pytest.mark.parametrize(
    "content",
    [
        'ok {"color": "RED"}',
        '```json\n{"color": "RED"}\n```',
        '<think>x</think>{"color": "RED"}',
        '{"color": "RED"}{"color": "GREEN"}',
        '{"color": "RED", "color": "GREEN"}',
        "[1]",
        "",
        None,
    ],
)
def test_prose_fence_think_two_objects_are_a_bad_reply(fake, content):
    fake(msg(content))
    with pytest.raises(al.LocalBadReply):
        al.LocalProvider().complete(MSGS, SPECS)


@pytest.mark.parametrize(
    "reply", [{}, {"message": "x"}, {"message": None}, "not a dict", None]
)
def test_missing_message_is_a_bad_reply(fake, reply):
    fake(reply)
    with pytest.raises(al.LocalBadReply):
        al.LocalProvider().complete(MSGS, SPECS)


def test_usd_is_zero_and_model_comes_from_the_response(fake):
    f = fake(msg(calls=call()))
    assert (
        al.LocalProvider(model="configured:1b").complete(MSGS, SPECS)["model"]
        == "qwen-test:35b"
    )
    f.reply = {"message": msg(calls=call())["message"]}
    out = al.LocalProvider(model="configured:1b").complete(MSGS, SPECS)
    assert out["model"] == "unknown" and out["usd"] == 0.0


def test_request_has_think_false_temperature_zero_and_num_predict(fake):
    f = fake(msg(calls=call()))
    al.LocalProvider(timeout=12.5, num_ctx=16384, num_predict=777).complete(MSGS, SPECS)
    body, timeout = f.bodies[0]
    assert body["think"] is False and body["stream"] is False and timeout == 12.5
    assert body["options"] == {"temperature": 0, "num_predict": 777, "num_ctx": 16384}
    assert al.LocalProvider(think=True).build_body(MSGS, SPECS)["think"] is True


def test_messages_are_converted_from_the_loop_and_the_anthropic_layout():
    loop = [
        *MSGS,
        {
            "role": "assistant",
            "content": {"tool": "open_page", "args": {"doc": "D"}, "reason": "r"},
        },
        {"role": "tool", "name": "open_page", "content": {"ok": True}},
    ]
    out = al.to_ollama_messages(loop, "skill text")
    assert out[0]["role"] == "system" and "skill text" in out[0]["content"]
    assert out[2]["tool_calls"][0]["function"]["name"] == "open_page"
    assert out[3] == {
        "role": "tool",
        "tool_name": "open_page",
        "content": '{"ok": true}',
    }
    blocks = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t",
                    "name": "open_page",
                    "input": {"doc": "D"},
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t", "content": "res"}],
        },
    ]
    o2 = al.to_ollama_messages(blocks)
    assert [m["role"] for m in o2] == ["system", "user", "assistant", "tool"]
    assert (
        o2[2]["tool_calls"][0]["function"]["arguments"]["doc"] == "D"
        and o2[3]["content"] == "res"
    )


def test_transport_failure_is_a_code_and_no_text_leaks(fake, caplog):
    fake(raises=RuntimeError(SENTINEL))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(al.LocalTransportError) as e:
        al.LocalProvider().complete([{"role": "user", "content": SENTINEL}], SPECS)
    assert (
        e.value.code == "transport_RuntimeError"
        and e.value.__context__ is None
        and e.value.__cause__ is None
    )
    assert SENTINEL not in str(e.value) + repr(e.value) + caplog.text


def test_bad_reply_error_holds_no_document_text(fake):
    fake(msg(SENTINEL))
    with pytest.raises(al.LocalBadReply) as e:
        al.LocalProvider().complete(MSGS, SPECS)
    assert SENTINEL not in str(e.value) + repr(e.value)


def test_a_url_that_differs_from_the_setting_sends_nothing(fake, monkeypatch):
    f = fake(msg(calls=call()))
    monkeypatch.setattr(
        model_transport, "endpoint", lambda p: "http://127.0.0.1:11434" + p
    )
    with pytest.raises(al.LocalTransportError) as e:
        al.LocalProvider(url="http://127.0.0.1:11435").complete(MSGS, SPECS)
    assert e.value.code == "url_mismatch" and f.bodies == []
    fake(msg(calls=call()))
    assert (
        al.LocalProvider(url="http://127.0.0.1:11434").complete(MSGS, SPECS)["tool"]
        == "open_page"
    )


def test_stats_are_numbers_and_models_seen_from_responses(fake):
    f = fake(
        msg(
            calls=call(),
            prompt_eval_count=100,
            eval_count=20,
            prompt_eval_duration=2_000_000_000,
            eval_duration=1_000_000_000,
            load_duration=5,
            total_duration=4_000_000_000,
        )
    )
    p = al.LocalProvider()
    assert p.stats["generation_tokens_per_second"] is None and p.stats["calls"] == 0
    p.complete(MSGS, SPECS)
    p.complete(MSGS, SPECS)
    s = p.stats
    assert (
        s["calls"] == 2
        and s["seconds"] >= 0
        and s["prompt_eval_count"] == 200
        and s["eval_count"] == 40
    )
    assert s["prompt_tokens_per_second"] == pytest.approx(50.0) and s[
        "generation_tokens_per_second"
    ] == pytest.approx(20.0)
    assert p.models_seen == ["qwen-test:35b"] and f.bodies


@pytest.fixture
def heavy(monkeypatch):
    from contextlib import contextmanager

    from app import heavy_lock

    log: list = []

    @contextmanager
    def held(kind, owner=None, wait_seconds=0, **kw):
        log.append(("lock", kind))
        yield

    monkeypatch.setattr(heavy_lock, "held", held)
    return log


def test_session_unloads_in_finally_even_when_a_call_raises(monkeypatch, heavy):
    unloaded = []
    monkeypatch.setattr(model_memory, "unload", lambda m: unloaded.append(m) or True)
    with pytest.raises(ValueError):
        with al.LocalProvider(model="m:1").session(wait_seconds=0):
            raise ValueError("boom")
    assert unloaded == ["m:1"] and heavy == [("lock", "agent_local_lead")]


def test_an_unload_error_is_swallowed_with_the_type_name_only(
    monkeypatch, heavy, caplog
):
    def boom(_m):
        raise OSError(SENTINEL)

    monkeypatch.setattr(model_memory, "unload", boom)
    with al.LocalProvider().session(wait_seconds=0):
        pass
    assert "OSError" in caplog.text and SENTINEL not in caplog.text


def test_engine_info_reads_version_and_ps_only(monkeypatch):
    seen = []

    def get(path, *, timeout, required=True):
        seen.append(path)
        if path == "/api/version":
            return {"version": "0.9.9"}
        return {
            "models": [
                {
                    "name": "m:1",
                    "size": 100,
                    "size_vram": 75,
                    "context_length": 8192,
                    "details": {"family": "qwen", "quantization_level": "Q4"},
                }
            ]
        }

    monkeypatch.setattr(model_transport, "get_json", get)
    info = al.engine_info()
    assert (
        seen == ["/api/version", "/api/ps"]
        and info["version"] == "0.9.9"
        and info["errors"] == []
    )
    assert (
        info["loaded"][0]["gpu_fraction"] == 0.75
        and info["loaded"][0]["size_vram"] == 75
    )


def test_engine_info_failure_is_the_type_name(monkeypatch):
    def get(path, *, timeout, required=True):
        raise ConnectionError(SENTINEL)

    monkeypatch.setattr(model_transport, "get_json", get)
    info = al.engine_info()
    assert info["errors"] == [
        "ConnectionError",
        "ConnectionError",
    ] and SENTINEL not in repr(info)


# ---- one internal retry on a bad reply; codes survive in the loop's safe_error_code


class Seq(Fake):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)

    def __call__(self, path, body, *, timeout):
        self.bodies.append((body, timeout))
        return self.replies.pop(0)


@pytest.fixture
def seq(monkeypatch):
    def install(*replies):
        f = Seq(replies)
        monkeypatch.setattr(model_transport, "post_json_retrying", f)
        return f

    return install


def test_a_bad_reply_gets_one_corrective_retry_then_succeeds(seq):
    f = seq(msg("I think so"), msg(calls=call()))
    p = al.LocalProvider()
    out = p.complete(MSGS, SPECS)
    assert out["tool"] == "open_page" and len(f.bodies) == 2
    assert f.bodies[1][0]["messages"][-1] == {"role": "user", "content": al.NUDGE}
    assert f.bodies[0][0]["messages"] == f.bodies[1][0]["messages"][:-1]
    assert p.stats["retries"] == 1 and p.stats["calls"] == 2


def test_two_bad_replies_are_a_bad_reply_and_never_a_third_call(seq):
    f = seq(msg("prose"), msg("more prose"), msg(calls=call()))
    p = al.LocalProvider()
    with pytest.raises(al.LocalBadReply):
        p.complete(MSGS, SPECS)
    assert len(f.bodies) == 2 and p.stats["retries"] == 1


def test_a_good_first_reply_does_not_retry_and_the_nudge_holds_no_document_text(seq):
    f = seq(msg(calls=call()))
    p = al.LocalProvider()
    p.complete([{"role": "user", "content": SENTINEL}], SPECS)
    assert len(f.bodies) == 1 and p.stats["retries"] == 0 and SENTINEL not in al.NUDGE


def test_a_transport_error_is_never_retried(fake):
    f = fake(raises=TimeoutError("t"))
    p = al.LocalProvider()
    with pytest.raises(al.LocalTransportError):
        p.complete(MSGS, SPECS)
    assert len(f.bodies) == 1 and p.stats["retries"] == 0


def test_the_loop_keeps_the_local_lead_code_and_only_the_class_name_of_foreign_errors():
    from app import agent_loop

    assert agent_loop.safe_error_code(al.LocalBadReply("no_final")) == "no_final"
    assert (
        agent_loop.safe_error_code(al.LocalTransportError("transport_ReadTimeout"))
        == "transport_ReadTimeout"
    )

    class Foreign(RuntimeError):
        code = "short_code"

    assert agent_loop.safe_error_code(Foreign("x")) == "Foreign"
