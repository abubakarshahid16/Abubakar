"""#501: a step with its own engine setting may use Claude while every other
step stays local - REASONING_PROVIDER=per_task.

Owner decision, 12 Oct 2026: Claude for the AI reader, the AI matcher and the
AI engineering check on the three approved test datasheets, up to USD 5; the
default stays local for everything else. Before this, a step's own setting
("DATASHEET_AI_READER=claude", "MATCH_ENGINE=claude") still needed the WHOLE
lane on (REASONING_PROVIDER=claude), which also sent CRS wording, the
applicability reasoning, the answer judge and chat to Claude.

What holds:
  * the provider switch is still the master switch and is checked FIRST:
    `ollama` refuses whatever a step's own setting says (r2 S5);
  * `per_task` opens the lane only for a step whose own engine says claude -
    and still needs both egress flags and a key;
  * a step WITHOUT an engine setting of its own stays local under `per_task`
    (`claude_unavailable`, `get_provider`, the three review routes);
  * `claude` means what it always meant.

Every transport here is a fake: nothing leaves the machine.
"""
from __future__ import annotations

import pytest

from app import claude_spend, comparison, datasheet_ai
from app import reasoning_provider as rp
from app.config import Settings, settings
from tests.test_model_matching import CANDIDATES, MODEL_SUBJECT, _claude_matcher, requirement, stub  # noqa: F401
from tests.test_model_matching import temp_storage  # noqa: F401 - autouse


@pytest.fixture
def lane(monkeypatch, tmp_path):
    """Both egress flags on and a key present: only the provider switch and
    the step's own engine setting decide."""
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-invented-key")


def test_the_provider_ships_local():
    assert Settings.model_fields["reasoning_provider"].default == "ollama"


@pytest.mark.parametrize("provider, engine, allowed, code", [
    ("per_task", "claude", True, None),
    ("per_task", "CLAUDE ", True, None),
    ("per_task", "ollama", False, rp.UNAVAILABLE_TASK_LOCAL),
    ("per_task", "off", False, rp.UNAVAILABLE_TASK_LOCAL),
    ("per_task", None, False, rp.UNAVAILABLE_TASK_LOCAL),
    ("claude", "claude", True, None),
    ("claude", "ollama", True, None),          # the whole lane: the step's own caller picks its engine
    ("ollama", "claude", False, rp.UNAVAILABLE_PROVIDER_OFF),     # THE MASTER SWITCH, first
    ("", "claude", False, rp.UNAVAILABLE_PROVIDER_OFF),
    ("off", "claude", False, rp.UNAVAILABLE_PROVIDER_OFF),
    ("per-task", "claude", False, rp.UNAVAILABLE_PROVIDER_OFF),   # a misspelt switch opens nothing
])
def test_when_a_step_with_its_own_engine_may_use_claude(lane, monkeypatch, provider, engine, allowed, code):
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    got, _why = rp.claude_unavailable_for_task(engine)
    assert (got is None) is allowed and got == code


@pytest.mark.parametrize("flag", ["STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS"])
def test_per_task_still_needs_both_egress_flags(lane, monkeypatch, flag):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setenv(flag, "false")
    assert rp.claude_unavailable_for_task("claude")[0] == rp.UNAVAILABLE_EGRESS_OFF


def test_per_task_still_needs_a_key(lane, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert rp.claude_unavailable_for_task("claude")[0] == rp.UNAVAILABLE_KEY_MISSING


def test_under_per_task_a_step_without_its_own_engine_stays_local(lane, monkeypatch):
    """CRS wording, applicability reasoning, the answer judge, chat, the
    review routes: they ask `claude_unavailable` / `get_provider`."""
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    assert rp.claude_unavailable()[0] == rp.UNAVAILABLE_PROVIDER_OFF
    assert rp.claude_available()[0] is False
    for role in ("reasoning", "labelling"):
        assert isinstance(rp.get_provider(role), rp.OllamaProvider)


# ------------------------------------------------------------- the matcher

def test_under_per_task_the_matcher_asks_claude_when_its_own_engine_says_so(stub, monkeypatch, tmp_path):  # noqa: F811
    local = stub((0, "should never be asked"))
    sent = _claude_matcher(monkeypatch, tmp_path, '{"choice": 0, "reason": "both are the shell pressure"}')
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    got = comparison.match_by_model(requirement(subject=MODEL_SUBJECT), CANDIDATES)
    assert got["fact"] is CANDIDATES[0] and local.calls == 0
    assert len(sent) == 2 and [e["step"] for e in claude_spend.entries()] == [comparison.MATCH_STEP] * 2


def test_under_per_task_the_matcher_stays_local_when_its_own_engine_is_local(stub, monkeypatch, tmp_path):  # noqa: F811
    local = stub((0, "both are the shell pressure"))
    sent = _claude_matcher(monkeypatch, tmp_path, '{"choice": 0, "reason": "x"}')
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "match_engine", "ollama")
    comparison.match_by_model(requirement(subject=MODEL_SUBJECT), CANDIDATES)
    assert sent == [] and local.calls >= 1


# -------------------------------------------------------------- the reader

def _reader_transport(monkeypatch):
    from app import reader_transport
    sent: list[dict] = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        return {"model": body["model"], "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"facts": []}'}],
                "usage": {"input_tokens": 100, "output_tokens": 10}}
    send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    return sent


def test_under_per_task_the_reader_gets_claude_only_when_its_own_setting_says_so(lane, monkeypatch):
    _reader_transport(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    call, why = datasheet_ai.model_call_for()
    assert why is None and call.engine == datasheet_ai.CLAUDE
    # asked for claude by a CALLER while the reader's own setting says local: refused
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    call, why = datasheet_ai.model_call_for("claude")
    assert call is None and rp.UNAVAILABLE_TASK_LOCAL in why


def test_the_master_switch_refuses_the_reader_whatever_its_own_setting_says(lane, monkeypatch):
    sent = _reader_transport(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    call, why = datasheet_ai.model_call_for()
    assert call is None and rp.UNAVAILABLE_PROVIDER_OFF in why and sent == []
