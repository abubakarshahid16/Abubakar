"""The three models the owner will use when the Claude lane opens.

Every request is built by the REAL builder and handed to a FAKE transport: no
API call of any kind, no key, no live database. Each path is asserted against
what the current Messages API answers 400 to on these models (temperature,
`budget_tokens`, `thinking: disabled`, forced `tool_choice`, assistant prefill).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    ai_engineering_check,
    answerability,
    applicability,
    chat_model,
    claude_models,
    claude_spend,
    comparison,
    crs_wording,
    datasheet_ai,
    field_naming,
    reader_api,
    reader_transport,
    rule_eval,
    standards_converter,
)
from app import reasoning_provider as rp
from app.ai import output_limits
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")

SONNET, OPUS, HAIKU = "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"
MODELS = (SONNET, OPUS, HAIKU)
KEY = "sk-ant-test-not-a-real-key"
LONG_AGO = "2000-01-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def rejected_fields(body: dict) -> list[str]:
    """What these three models answer 400 to, read off one request body."""
    problems = []
    if "temperature" in body or "top_p" in body or "top_k" in body:
        problems.append("sampling parameter")
    thinking = body.get("thinking") or {}
    if "budget_tokens" in thinking or thinking.get("type") in ("enabled", "disabled"):
        problems.append(f"thinking {thinking}")
    if (body.get("tool_choice") or {}).get("type") in ("any", "tool"):
        problems.append(f"forced tool_choice {body['tool_choice']}")
    messages = body.get("messages") or []
    if messages and messages[-1].get("role") == "assistant":
        problems.append("assistant prefill")
    return problems


def _reply(model, text='{"answer": "yes"}', stop="end_turn", usage=None):
    return {
        "model": model,
        "stop_reason": stop,
        "content": [{"type": "text", "text": text}],
        "usage": usage or {"input_tokens": 100, "output_tokens": 20},
    }


def _send(seen, reply):
    def send(url, *, headers, body, timeout):
        seen.append(body)
        return reply

    return send


def _packet(**kw):
    base = {
        "prompt": "Is it?",
        "num_ctx": 4096,
        "num_predict": 200,
        "step": "test-step",
    }
    base.update(kw)
    return rp.Packet(**base)


def _cfg(model=SONNET):
    return reader_api.ReaderSettings(
        enabled=True, allow_public_egress=True, model=model
    )


# ----------------------------------------------- every path, all three models


@pytest.mark.parametrize("model", MODELS)
def test_the_standards_reader_call_carries_no_rejected_field(model):
    seen = []
    reader_api.call_claude(
        "a sentence",
        transport=_send(seen, _reply(model)),
        cfg=_cfg(model),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    assert seen and rejected_fields(seen[0]) == [] and seen[0]["model"] == model


@pytest.mark.parametrize("model", MODELS)
def test_the_provider_call_carries_no_rejected_field(model):
    seen = []
    rp.ClaudeProvider(model, transport=_send(seen, _reply(model)), step="s").reason(
        _packet(temperature=0.7, json_schema={"type": "object"})
    )
    assert seen and rejected_fields(seen[0]) == []


@pytest.mark.parametrize("model", MODELS)
def test_a_thinking_call_uses_adaptive_thinking_never_a_budget(model):
    seen = []
    rp.ClaudeProvider(model, transport=_send(seen, _reply(model)), step="s").reason(
        _packet(thinking_budget=2000, num_predict=4000)
    )
    assert seen[0]["thinking"] == {"type": "adaptive"}
    assert rejected_fields(seen[0]) == []


def test_an_older_model_that_only_takes_a_budget_still_gets_one():
    seen = []
    rp.ClaudeProvider(
        "claude-haiku-4-5-20251001", transport=_send(seen, _reply("x")), step="s"
    ).reason(_packet(thinking_budget=2000, num_predict=4000))
    assert seen[0]["thinking"] == {"type": "enabled", "budget_tokens": 2000}


@pytest.mark.parametrize("model", MODELS)
def test_a_streamed_call_carries_no_rejected_field(model):
    seen = []

    def send(url, *, headers, body, timeout, cancel=None):
        seen.append(body)
        yield from _stream_events(_reply(model, "fine"))

    rp.ClaudeProvider(model, stream_transport=send, step="s").stream(
        _packet(thinking_budget=2000, num_predict=4000, temperature=0.5),
        lambda _p: None,
    )
    assert seen and rejected_fields(seen[0]) == []


class _Batches:
    def __init__(self, model, stop="end_turn", text='{"answer": "yes"}'):
        self.model, self.stop, self.text, self.created = model, stop, text, []

    def batch_create(self, url, *, headers, requests):
        self.created.extend(requests)
        return {
            "id": "b1",
            "processing_status": "ended",
            "results_url": "https://api.anthropic.com/r",
        }

    def batch_retrieve(self, url, batch_id, *, headers):
        raise AssertionError("already ended")

    def batch_results(self, url, *, headers):
        return [
            {
                "custom_id": r["custom_id"],
                "result": {
                    "type": "succeeded",
                    "message": _reply(self.model, self.text, self.stop),
                },
            }
            for r in self.created
        ]


@pytest.mark.parametrize("model", MODELS)
def test_a_batch_request_carries_no_rejected_field_and_is_marked_batch(model):
    client = _Batches(model)
    rp.ClaudeProvider(model, step="s").reason_batch(
        [_packet(temperature=0.3)], client=client
    )
    assert client.created and rejected_fields(client.created[0]["params"]) == []
    settled = [e for e in claude_spend.entries() if e.get("settles")]
    assert settled and settled[0]["batch"] is True and settled[0]["model"] == model


@pytest.mark.parametrize("model", MODELS)
def test_the_datasheet_reader_carries_no_rejected_field(model, monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "claude_reasoning_model", model)
    monkeypatch.setattr(
        reader_transport,
        "transport",
        lambda: _send(seen, _reply(model, '{"facts": []}')),
    )
    call, why = datasheet_ai.model_call_for("claude")
    assert why is None
    datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, call)
    assert seen and rejected_fields(seen[0]) == []


@pytest.mark.parametrize("model", MODELS)
def test_the_matcher_carries_no_rejected_field(model, monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "claude_reasoning_model", model)
    monkeypatch.setattr(settings, "match_engine", "claude")
    monkeypatch.setattr(
        reader_transport, "transport", lambda: _send(seen, _reply(model, '{"n": 1}'))
    )
    text, why = comparison._ask_claude_for_a_pair("which pair?")
    assert why is None and text
    assert seen and rejected_fields(seen[0]) == []


@pytest.mark.parametrize("model", MODELS)
def test_the_standards_converter_packet_carries_no_rejected_field(model, monkeypatch):
    seen = []
    monkeypatch.setattr(
        standards_converter.claude_approved,
        "carrying",
        lambda _ids: contextlib.nullcontext(),
    )
    provider = rp.ClaudeProvider(model, transport=_send(seen, _reply(model, "[]")))
    rows = [
        {
            "id": "r1",
            "requirement_type": sorted(standards_converter.CONVERTIBLE_TYPES)[0],
            "text": "x",
            "section": "1",
        }
    ]
    monkeypatch.setattr(standards_converter, "requirements_of", lambda _c, _d: rows)
    monkeypatch.setattr(standards_converter, "require_family", lambda _s: None)
    monkeypatch.setattr(standards_converter, "require_known_type", lambda _t: None)
    monkeypatch.setattr(standards_converter.rule_roles, "form", lambda _t: ({}, {}, {}))
    monkeypatch.setattr(standards_converter, "system_text", lambda _t, _d: "system")
    out = standards_converter.convert(None, "d1", "SAES-X-1", "pump", provider)
    assert seen and rejected_fields(seen[0]) == []
    assert out.model == model


@pytest.mark.parametrize("model", MODELS)
def test_the_general_chat_path_carries_no_rejected_field(model, monkeypatch):
    seen = []
    engine = rp.ClaudeProvider(model, transport=_send(seen, _reply(model, "fine")))
    monkeypatch.setattr(chat_model, "provider", lambda _preference: engine)
    chat_model.generate("sys", "hello", temperature=0.5, timeout=30.0)
    assert seen and rejected_fields(seen[0]) == []


def _scripted_chat(monkeypatch, model, payloads, calls):
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(json.loads(json.dumps(body, default=str)))
        i = min(n["i"], len(payloads) - 1)
        n["i"] += 1
        yield from _stream_events(payloads[i])

    real = rp.ClaudeProvider
    monkeypatch.setattr(settings, "claude_reasoning_model", model)
    monkeypatch.setattr(
        rp,
        "get_provider",
        lambda role="reasoning", *, step=None: real(
            model, step=step, stream_transport=send
        ),
    )


def _tool_round(model, doc):
    return {
        "model": model,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 200, "output_tokens": 30},
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_document",
                "input": {"document_id": doc},
            }
        ],
    }


@pytest.mark.parametrize("model", MODELS)
def test_the_chat_tool_loop_carries_no_rejected_field_on_any_round(model, monkeypatch):
    """A complex question (thinking on), a tool round, then the tool cap's
    `tool_choice: none`: no round may carry a rejected field or end on an
    assistant turn."""
    monkeypatch.setattr(settings, "chat_tool_max_calls", 1)
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    _scripted_chat(
        monkeypatch,
        model,
        [_tool_round(model, doc), _reply(model, "Nothing more to add.")],
        calls,
    )
    convo = client.post("/api/conversations").json()["id"]
    client.post(
        f"/api/conversations/{convo}/ask",
        json={
            "question": "compare standard A and standard B",
            "document_id": doc,
            "tier": "generated",
        },
    )
    assert len(calls) >= 2
    assert any(body.get("thinking") == {"type": "adaptive"} for body in calls)
    for body in calls:
        assert rejected_fields(body) == [], body.get("thinking")


# ------------------------------------------------------------------- prices


@pytest.mark.parametrize(
    "model,expected",
    [
        (SONNET, (2.0, 10.0, 2.5, 0.20)),
        (OPUS, (4.0, 20.0, 5.0, 0.20)),
        (HAIKU, (0.10, 0.50, 0.125, 0.01)),
        ("claude-sonnet-5", (2.0, 10.0, 2.5, 0.20)),
        ("claude-opus-5", (5.0, 25.0, 6.25, 0.50)),
        ("claude-haiku-4-5-20251001", (1.0, 5.0, 1.25, 0.10)),
    ],
)
def test_each_id_finds_its_own_family_price(model, expected):
    assert claude_spend.price_for(model) == expected


def test_a_haiku_prompt_at_100k_tokens_is_cheap_and_one_token_more_is_not():
    at = {"input_tokens": 100_000, "output_tokens": 1_000_000}
    over = {"input_tokens": 100_001, "output_tokens": 1_000_000}
    assert claude_spend.cost_usd(HAIKU, at) == pytest.approx(0.01 + 0.50, abs=1e-6)
    assert claude_spend.cost_usd(HAIKU, over) == pytest.approx(
        100_001 * 0.50 / 1e6 + 2.50, abs=1e-6
    )


def test_cached_tokens_count_towards_the_haiku_prompt_length():
    usage = {"input_tokens": 10, "cache_read_input_tokens": 100_000, "output_tokens": 0}
    assert claude_spend.cost_usd(HAIKU, usage) == pytest.approx(
        (10 * 0.50 + 100_000 * 0.05) / 1e6
    )


def test_the_haiku_worst_case_uses_the_rate_card_its_prompt_falls_on():
    short = claude_spend.worst_case_usd(HAIKU, 3_000, 5_000)
    assert short == pytest.approx((1_001 * 0.125 + 5_000 * 0.50) / 1e6)
    long = claude_spend.worst_case_usd(HAIKU, 300_003, 5_000)
    assert long == pytest.approx((100_002 * 0.625 + 5_000 * 2.50) / 1e6)


def test_the_long_prompt_rate_is_haiku_only():
    usage = {"input_tokens": 150_000, "output_tokens": 0}
    assert claude_spend.cost_usd(SONNET, usage) == pytest.approx(0.30)


# ----------------------------------------------------- stop_reason "refusal"


def _refusal(model=SONNET, text='{"partial": true}'):
    return {
        **_reply(model, text, "refusal"),
        "stop_details": {"type": "refusal", "category": "cyber"},
    }


def test_a_refusal_with_partial_text_is_no_text_on_the_reader_lane():
    assert reader_api.response_text(_refusal()) == ""
    assert output_limits.state_of_payload(_refusal()) == output_limits.UNKNOWN
    assert output_limits.state_of("refusal", "some words") == output_limits.UNKNOWN


def test_a_refusal_is_could_not_read_through_the_route_model_call():
    call = output_limits.model_call_for(
        lambda *a, **k: _refusal(),
        output_limits.ROUTE_MATCH,
        cfg=_cfg(),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    with pytest.raises(output_limits.Unreadable):
        call("anything")


def test_a_refusal_through_the_provider_is_empty_uncached_and_still_charged():
    seen = []
    provider = rp.ClaudeProvider(SONNET, transport=_send(seen, _refusal()), step="s")
    packet = _packet(json_schema={"type": "object"})
    response = provider.reason(packet)
    assert response.text == "" and response.finish_reason == "refusal"
    assert response.schema_errors, "an empty answer must fail its schema"
    assert output_limits.state_of_response(response) == output_limits.UNKNOWN
    assert response.cost_usd > 0
    provider.reason(packet)
    assert len(seen) == 2, "a refusal must never be served from the response cache"


def test_a_refusal_in_a_stream_is_a_charged_stated_failure():
    def send(url, *, headers, body, timeout, cancel=None):
        yield from _stream_events(_refusal(text="half an answer"))

    provider = rp.ClaudeProvider(SONNET, stream_transport=send, step="s")
    with pytest.raises(rp.ProviderRefused, match="declined") as refused:
        provider.stream(_packet(), lambda _p: None)
    assert refused.value.cost_usd > 0
    settled = [e for e in claude_spend.entries() if e.get("settles")]
    assert settled[0]["finish_reason"] == "refusal"


def test_a_refused_batch_request_is_could_not_read():
    client = _Batches(SONNET, stop="refusal")
    [response] = rp.ClaudeProvider(SONNET, step="s").reason_batch(
        [_packet(json_schema={"type": "object"})], client=client
    )
    assert response.text == "" and response.schema_errors


def test_a_refused_sentence_is_named_not_passed():
    call = reader_api.model_call_via(
        lambda *a, **k: _refusal(text='{"proposals": []}'),
        cfg=_cfg(),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    out = reader_api.read_sentence("The noise shall not exceed 90 dB(A).", call)
    assert reader_api.Reason.MODEL_MALFORMED.value in str(out)


def test_a_refused_converter_batch_is_unreadable_never_a_pass(monkeypatch):
    monkeypatch.setattr(
        standards_converter.claude_approved,
        "carrying",
        lambda _ids: contextlib.nullcontext(),
    )
    provider = rp.ClaudeProvider(SONNET, transport=_send([], _refusal(text="[]")))
    rows = [
        {
            "id": "r1",
            "requirement_type": sorted(standards_converter.CONVERTIBLE_TYPES)[0],
            "text": "x",
            "section": "1",
        }
    ]
    monkeypatch.setattr(standards_converter, "requirements_of", lambda _c, _d: rows)
    monkeypatch.setattr(standards_converter, "require_family", lambda _s: None)
    monkeypatch.setattr(standards_converter, "require_known_type", lambda _t: None)
    monkeypatch.setattr(standards_converter.rule_roles, "form", lambda _t: ({}, {}, {}))
    monkeypatch.setattr(standards_converter, "system_text", lambda _t, _d: "system")
    out = standards_converter.convert(None, "d1", "SAES-X-1", "pump", provider)
    assert out.unreadable_batches == 1


def test_a_chat_refusal_is_a_stated_failure_never_an_empty_answer(monkeypatch):
    client = TestClient(app)
    doc = upload(client)
    calls: list = []
    _scripted_chat(
        monkeypatch, SONNET, [_tool_round(SONNET, doc), _refusal(text="")], calls
    )
    convo = client.post("/api/conversations").json()["id"]
    body = client.post(
        f"/api/conversations/{convo}/ask",
        json={
            "question": "tell me about this document",
            "document_id": doc,
            "tier": "generated",
        },
    ).json()
    assert len(calls) == 2
    assert body["answer_type"] == "model_unavailable" and not body["answer"]


# --------------------------------------------- the model actually used, recorded


def _settled(model, step, *, usage=None, finish="stop", requested="asked-for"):
    held = claude_spend.reserve(step, 0.01, model=requested, prompt_sha256="x")
    return claude_spend.settle(
        held,
        model=model,
        usage=usage or {"input_tokens": 5, "output_tokens": 5},
        finish_reason=finish,
    )


def test_the_ledger_and_the_response_name_the_model_that_answered_not_the_one_asked():
    response = rp.ClaudeProvider(
        SONNET, transport=_send([], _reply("answered-by")), step="s"
    ).reason(_packet())
    assert response.model_tag == "answered-by"
    settled = [e for e in claude_spend.entries() if e.get("settles")]
    assert settled[0]["model"] == "answered-by"


def test_a_metered_call_keeps_the_model_that_answered():
    call = claude_spend.metered(_send([], _reply("answered-by")), "s")
    call(
        "https://x",
        headers={},
        body={"model": "asked-for", "max_tokens": 1, "messages": []},
        timeout=1.0,
    )
    assert call.last_model == "answered-by"


def test_models_used_reads_only_answers_of_this_window():
    _settled("answered-a", "review-step")
    _settled("answered-b", "other-step")
    claude_spend.reserve("review-step", 0.01, model="still-open", prompt_sha256="y")
    assert claude_spend.models_used(since=LONG_AGO) == ["answered-a", "answered-b"]
    assert claude_spend.models_used(since=LONG_AGO, steps={"other-step"}) == [
        "answered-b"
    ]
    assert claude_spend.models_used(since="2999-01-01T00:00:00+00:00") == []


def test_models_used_leaves_out_chat_when_asked_and_a_call_that_never_answered():
    _settled("chat-model", "chat")
    _settled("review-model", "review-step")
    held = claude_spend.reserve(
        "review-step", 0.5, model="never-answered", prompt_sha256="z"
    )
    claude_spend.settle_failure(held, RuntimeError("read timeout"))
    assert claude_spend.models_used(since=LONG_AGO, exclude_prefixes=("chat",)) == [
        "review-model"
    ]


def test_the_datasheet_reader_names_the_model_that_answered(monkeypatch):
    monkeypatch.setattr(settings, "claude_reasoning_model", "asked-for")
    monkeypatch.setattr(
        reader_transport,
        "transport",
        lambda: _send([], _reply("answered-by", '{"facts": []}')),
    )
    call, why = datasheet_ai.model_call_for("claude")
    assert why is None
    assert output_limits.model_used(call) == "asked-for", (
        "before any answer: what was asked"
    )
    datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, call)
    assert output_limits.model_used(call) == "answered-by"


# ---------------------------- thinking counts inside max_tokens: the short routes

FLOOR = 4096


def _matcher_body(model, monkeypatch, reply=None):
    seen = []
    monkeypatch.setattr(settings, "claude_reasoning_model", model)
    monkeypatch.setattr(settings, "match_engine", "claude")
    monkeypatch.setattr(
        reader_transport,
        "transport",
        lambda: _send(seen, reply or _reply(model, '{"n": 1}')),
    )
    outcome = comparison._ask_claude_for_a_pair("which pair?")
    return seen, outcome


@pytest.mark.parametrize("model", MODELS)
def test_the_sentence_reader_has_room_to_think_at_low_effort(model):
    seen = []
    reader_api.call_claude(
        "a sentence",
        transport=_send(seen, _reply(model)),
        cfg=_cfg(model),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    assert seen[0]["max_tokens"] == FLOOR
    assert seen[0]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("model", MODELS)
def test_the_matcher_has_room_to_think_at_the_default_effort(model, monkeypatch):
    seen, _outcome = _matcher_body(model, monkeypatch)
    assert seen[0]["max_tokens"] == FLOOR
    assert "output_config" not in seen[0]


@pytest.mark.parametrize("model", MODELS)
def test_a_labelling_packet_has_room_to_think_at_low_effort(model):
    seen = []
    rp.ClaudeProvider(
        model, transport=_send(seen, _reply(model)), step=field_naming.NAMING_STEP
    ).reason(_packet(num_predict=300))
    assert seen[0]["max_tokens"] == FLOOR
    assert seen[0]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("model", MODELS)
def test_the_datasheet_reader_keeps_its_cap_and_reads_at_low_effort(model, monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "claude_reasoning_model", model)
    monkeypatch.setattr(settings, "datasheet_ai_claude_max_tokens", 8192)
    monkeypatch.setattr(
        reader_transport,
        "transport",
        lambda: _send(seen, _reply(model, '{"facts": []}')),
    )
    call, _why = datasheet_ai.model_call_for("claude")
    datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, call)
    assert seen[0]["max_tokens"] == 8192
    assert seen[0]["output_config"] == {"effort": "low"}


def test_an_effort_the_caller_chose_wins_and_chat_keeps_the_model_default():
    seen = []
    provider = rp.ClaudeProvider(
        SONNET, transport=_send(seen, _reply(SONNET)), step="s"
    )
    provider.reason(_packet(effort="high"))
    provider.reason(_packet(prompt="other", step="chat"))
    assert seen[0]["output_config"] == {"effort": "high"}
    assert "output_config" not in seen[1]
    assert seen[1]["max_tokens"] == FLOOR


@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-haiku-4-5-20251001"])
def test_an_older_model_keeps_its_cap_and_gets_no_effort(model):
    seen = []
    reader_api.call_claude(
        "a sentence",
        transport=_send(seen, _reply(model)),
        cfg=_cfg(model),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    assert seen[0]["max_tokens"] == 512
    assert "output_config" not in seen[0]


@pytest.mark.parametrize(
    "model,per_million", [(SONNET, 10.0), (OPUS, 20.0), (HAIKU, 0.50)]
)
def test_the_budget_gate_sees_the_raised_limit(model, per_million):
    assert claude_spend.worst_case_usd(model, 0, 200) == pytest.approx(
        claude_spend.worst_case_usd(model, 0, FLOOR)
    )
    assert claude_spend.worst_case_usd(model, 0, 200) >= FLOOR * per_million / 1e6


def test_the_budget_gate_is_unchanged_for_an_older_model():
    low = claude_spend.worst_case_usd("claude-sonnet-5", 0, 200)
    assert low < claude_spend.worst_case_usd("claude-sonnet-5", 0, FLOOR)


def test_a_cap_above_the_floor_is_never_lowered():
    assert claude_spend.output_cap(SONNET, 8192) == 8192
    assert claude_spend.output_cap(SONNET, 200) == FLOOR


# ----------------- effort comes from the route's name, never from the size of its cap

JUDGEMENT_STEPS = (
    comparison.MATCH_STEP,
    answerability.JUDGE_STEP,
    ai_engineering_check.STEP,
    applicability.SCOPE_REASONING_STEP,
    crs_wording.STEP,
    "standards_convert:SAES-X-1",
    "chat",
)
JUDGEMENT_ROUTES = (
    output_limits.ROUTE_MATCH,
    output_limits.ROUTE_RECHECK,
    output_limits.ROUTE_APPLICABILITY,
    output_limits.ROUTE_CLAUSE_APPLICABILITY,
    output_limits.ROUTE_ENGINEERING_CHECK,
    output_limits.ROUTE_SELECT_STANDARDS,
    output_limits.ROUTE_CRS_WORDING,
)


@pytest.mark.parametrize("cap", [300, 4000, 4200, 12000])
@pytest.mark.parametrize("step", JUDGEMENT_STEPS)
@pytest.mark.parametrize("model", MODELS)
def test_a_judgement_step_never_gets_low_effort_from_its_cap(model, step, cap):
    seen = []
    rp.ClaudeProvider(model, transport=_send(seen, _reply(model)), step=step).reason(
        _packet(num_predict=cap)
    )
    assert "output_config" not in seen[0]
    assert seen[0]["max_tokens"] == max(cap, FLOOR)


@pytest.mark.parametrize("route", JUDGEMENT_ROUTES)
@pytest.mark.parametrize("model", MODELS)
def test_a_judgement_route_never_gets_low_effort_from_its_cap(model, route):
    seen = []
    call = output_limits.model_call_for(
        _send(seen, _reply(model)),
        route,
        cfg=_cfg(model),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    call("a question")
    assert "output_config" not in seen[0]


@pytest.mark.parametrize("cap", [300, 4000, 4200, 12000])
@pytest.mark.parametrize("step", [field_naming.NAMING_STEP, rule_eval.MODEL_STEP])
def test_a_label_or_verified_reading_is_low_effort_at_any_cap(step, cap):
    seen = []
    rp.ClaudeProvider(SONNET, transport=_send(seen, _reply(SONNET)), step=step).reason(
        _packet(num_predict=cap)
    )
    assert seen[0]["output_config"] == {"effort": "low"}


def test_the_two_route_lists_do_not_overlap_and_name_what_is_tested():
    low, default = claude_models.LOW_EFFORT_ROUTES, claude_models.MODEL_DEFAULT_ROUTES
    assert not low & default
    assert {field_naming.NAMING_STEP, rule_eval.MODEL_STEP} <= low
    assert output_limits.ROUTE_DATASHEET_READ in low
    assert set(JUDGEMENT_ROUTES) <= default
    assert {s for s in JUDGEMENT_STEPS if ":" not in s} <= default


# ---------------------------------------------- the model a request names by default


def _lane_on_with_no_env(monkeypatch):
    monkeypatch.setattr(settings, "claude_reasoning_model", SONNET)
    monkeypatch.setattr(settings, "standards_reader_model", "")


def test_an_unset_reader_model_follows_the_reasoning_model(monkeypatch):
    _lane_on_with_no_env(monkeypatch)
    assert reader_api.ReaderSettings.from_env().model == SONNET


def test_the_recheck_route_sends_the_reasoning_model_with_no_cfg(monkeypatch):
    _lane_on_with_no_env(monkeypatch)
    seen = []
    output_limits.model_call_for(
        _send(seen, _reply(SONNET)), output_limits.ROUTE_RECHECK
    )("a question")
    assert seen[0]["model"] == SONNET


def test_the_reader_model_setting_and_environment_win_in_that_order(monkeypatch):
    _lane_on_with_no_env(monkeypatch)
    monkeypatch.setattr(settings, "standards_reader_model", OPUS)
    assert reader_api.ReaderSettings.from_env().model == OPUS
    monkeypatch.setenv("STANDARDS_READER_MODEL", HAIKU)
    assert reader_api.ReaderSettings.from_env().model == HAIKU


def test_an_injected_environment_is_still_obeyed_exactly(monkeypatch):
    _lane_on_with_no_env(monkeypatch)
    assert (
        reader_api.ReaderSettings.from_env({}).model == reader_api.ReaderSettings.model
    )


def test_the_example_env_names_the_reader_model():
    example = Path(__file__).parents[1] / ".env.example"
    assert "STANDARDS_READER_MODEL" in example.read_text(encoding="utf-8")


def test_a_cache_hit_counts_as_a_model_used():
    claude_spend.record(
        step="review-step",
        model="answered-before",
        usage={},
        prompt_sha256="x",
        wall_time_s=0.0,
        finish_reason="cache_hit",
    )
    assert claude_spend.models_used(since=LONG_AGO) == ["answered-before"]


# ------------------------------------- a cut-off answer: could-not-read, once


def _cut(model=SONNET, text='{"n": 1'):
    return _reply(model, text, "max_tokens")


def test_a_cut_off_matcher_answer_is_named_and_asked_once(monkeypatch):
    seen, outcome = _matcher_body(SONNET, monkeypatch, reply=_cut())
    assert outcome == (None, comparison.MODEL_TRUNCATED)
    assert len(seen) == 1


def test_a_cut_off_sentence_is_could_not_read_even_when_the_text_parses():
    seen = []
    call = reader_api.model_call_via(
        _send(seen, _cut(text='{"proposals": []}')),
        cfg=_cfg(),
        env={"ANTHROPIC_API_KEY": KEY},
    )
    out = reader_api.read_sentence("The noise shall not exceed 90 dB(A).", call)
    assert out["error"] == reader_api.Reason.MODEL_MALFORMED.value
    assert len(seen) == 1, "no second read of an answer already cut off"


def test_a_cut_off_labelling_answer_is_truncated_uncached_and_not_resent():
    seen = []
    provider = rp.ClaudeProvider(
        SONNET, transport=_send(seen, _cut(text='{"a": 1}')), step="labels"
    )
    packet = _packet(num_predict=300)
    response = provider.reason(packet)
    assert response.truncated
    assert output_limits.state_of_response(response) == output_limits.TRUNCATED
    assert len(seen) == 1
    with pytest.raises(output_limits.Truncated):
        output_limits.complete_text(response, "labels")
    provider.reason(packet)
    assert len(seen) == 2, "the caller asked again: never served from the cache"


# --------------------------------------------------- the switch stays where it is


def test_the_shipped_default_keeps_the_lane_local():
    assert type(settings).model_fields["reasoning_provider"].default == "ollama"
