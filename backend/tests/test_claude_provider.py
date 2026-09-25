"""The Claude reasoning provider (owner decision 2026-09-25): selection,
fallback, the USD budget stop, the ledger, the key never in logs, and the JSON
schema gate. No network: the transport is injected."""
import json
import logging

import pytest

from app import claude_spend, reasoning_provider as rp
from app.config import settings

KEY = "sk-ant-test-THIS-MUST-NEVER-APPEAR-0123456789"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _transport(text='{"answer": "yes"}', usage=None, model="claude-sonnet-5", seen=None, stop="end_turn"):
    def send(url, *, headers, body, timeout):
        if seen is not None:
            seen.append({"url": url, "headers": headers, "body": body})
        return {"model": model, "stop_reason": stop,
                "content": [{"type": "text", "text": text}],
                "usage": usage or {"input_tokens": 1000, "output_tokens": 100}}
    return send


def _packet(**kw):
    base = {"prompt": "Is it?", "num_ctx": 4096, "num_predict": 200, "step": "test-step"}
    base.update(kw)
    return rp.Packet(**base)


# ----------------------------------------------------------------- selection

def test_claude_is_selected_only_when_everything_is_in_place():
    """THE MUTATION TARGET (M565)."""
    assert isinstance(rp.get_provider(), rp.ClaudeProvider)
    assert rp.get_provider().requested_model == settings.claude_reasoning_model
    assert rp.get_provider("labelling").requested_model == settings.claude_labelling_model


def test_provider_ollama_means_ollama(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert isinstance(rp.get_provider(), rp.OllamaProvider)


def test_missing_key_falls_back_to_ollama_and_says_why(monkeypatch, caplog):
    """THE MUTATION TARGET (M566)."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with caplog.at_level(logging.WARNING):
        assert isinstance(rp.get_provider(), rp.OllamaProvider)
    assert "no ANTHROPIC_API_KEY" in caplog.text


def test_egress_flags_off_fall_back_to_ollama(monkeypatch):
    """The provider switch is ANDed with the two egress flags, never ORed."""
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", False)
    assert isinstance(rp.get_provider(), rp.OllamaProvider)


# -------------------------------------------------------------- the call

def test_a_call_records_model_tokens_cost_and_no_text(tmp_path):
    seen = []
    r = rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(
        _packet(prompt="SECRET DOCUMENT SENTENCE", system="STANDARD TEXT"))
    assert (r.provider, r.model_tag, r.finish_reason) == ("claude", "claude-sonnet-5", "stop")
    assert r.cost_usd == pytest.approx((1000 * 2.0 + 100 * 10.0) / 1e6)
    ledger = settings.claude_spend_log.read_text(encoding="utf-8")
    assert json.loads(ledger)["step"] == "test-step"
    assert "SECRET DOCUMENT" not in ledger and "STANDARD TEXT" not in ledger
    assert seen[0]["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen[0]["body"]["model"] == "claude-sonnet-5"


def test_max_tokens_stop_is_reported_as_truncated():
    r = rp.ClaudeProvider(transport=_transport(stop="max_tokens")).reason(_packet())
    assert r.truncated


def test_the_key_never_reaches_a_log_the_ledger_or_an_error(caplog):
    """THE MUTATION TARGET (M567)."""
    def failing(url, *, headers, body, timeout):
        raise RuntimeError("429 from api.anthropic.com (rate_limit_error)")
    with caplog.at_level(logging.DEBUG):
        rp.ClaudeProvider(transport=_transport()).reason(_packet(prompt="first"))
        with pytest.raises(rp.ProviderRefused) as caught:
            rp.ClaudeProvider(transport=failing).reason(_packet(prompt="second"))
    assert KEY not in caplog.text
    assert KEY not in str(caught.value)
    assert KEY not in settings.claude_spend_log.read_text(encoding="utf-8")


# ------------------------------------------------------------------ budget

def test_the_step_cap_stops_the_call_before_it_leaves(monkeypatch):
    """THE MUTATION TARGET (M568)."""
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.001)
    seen = []
    with pytest.raises(claude_spend.BudgetExceeded):
        rp.ClaudeProvider(transport=_transport(seen=seen)).reason(_packet(num_predict=4000))
    assert seen == []                       # nothing went out


def test_the_total_cap_counts_every_step(monkeypatch):
    """THE MUTATION TARGET (M569)."""
    for _ in range(3):
        claude_spend.record(step="earlier-step", model="claude-sonnet-5",
                            usage={"input_tokens": 1_000_000}, prompt_sha256="x",
                            wall_time_s=0, finish_reason="stop")
    monkeypatch.setattr(settings, "claude_budget_usd_total", 6.001)
    with pytest.raises(claude_spend.BudgetExceeded, match="total"):
        rp.ClaudeProvider(transport=_transport()).reason(_packet(step="new-step"))


def test_cache_tokens_are_priced():
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000,
             "cache_read_input_tokens": 1_000_000}
    assert claude_spend.cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(1.25 + 0.10)


def test_an_unknown_model_is_priced_at_the_dearest_rate():
    assert claude_spend.price_for("claude-future-9") == max(claude_spend.PRICES.values())


# ----------------------------------------------------------- response cache

def test_a_repeat_call_is_served_from_cache_at_zero_cost():
    """THE MUTATION TARGET (M571)."""
    seen = []
    first = rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(_packet())
    again = rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(_packet())
    assert len(seen) == 1 and again.text == first.text and again.cost_usd == 0.0
    assert claude_spend.spent("test-step") == pytest.approx(first.cost_usd)


def test_a_new_prompt_version_or_model_is_not_a_cache_hit():
    seen = []
    rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(_packet())
    rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(_packet(prompt_version="v2"))
    rp.ClaudeProvider("claude-haiku-4-5", transport=_transport(seen=seen)).reason(_packet())
    assert len(seen) == 3


def test_a_truncated_answer_is_not_cached():
    seen = []
    rp.ClaudeProvider(transport=_transport(seen=seen, stop="max_tokens")).reason(_packet())
    rp.ClaudeProvider(transport=_transport(seen=seen)).reason(_packet())
    assert len(seen) == 2


# ------------------------------------------------------------- schema gate

SCHEMA = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["a", "b"]},
                                          "quote": {"type": ["string", "null"]}},
          "required": ["decision", "quote"]}


@pytest.mark.parametrize("text,ok", [
    ('{"decision": "a", "quote": null}', True),
    ('```json\n{"decision": "b", "quote": "x"}\n```', True),
    ('{"decision": "c", "quote": null}', False),     # enum
    ('{"decision": "a"}', False),                    # required
    ('{"decision": "a", "quote": 3}', False),        # type
    ("I think a", False),                            # not JSON
])
def test_the_schema_gate_is_code_not_the_model(text, ok):
    """THE MUTATION TARGET (M570)."""
    r = rp.ClaudeProvider(transport=_transport(text=text)).reason(_packet(json_schema=SCHEMA))
    assert (r.schema_errors == ()) is ok


def test_a_model_that_rejects_temperature_is_not_sent_one():
    """THE MUTATION TARGET (M573): Sonnet 5 answers 400 when temperature is sent."""
    seen = []
    rp.ClaudeProvider("claude-sonnet-5", transport=_transport(seen=seen)).reason(_packet())
    rp.ClaudeProvider("claude-haiku-4-5-20251001", transport=_transport(seen=seen)).reason(_packet())
    assert "temperature" not in seen[0]["body"]
    assert seen[1]["body"]["temperature"] == 0.0
