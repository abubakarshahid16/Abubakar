"""Division scope's Claude route: its own engine setting, every Claude gate, no local engine.

Fake transport only; no socket, no real call. Invented standard text and values (rule 13).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import (
    ai_applicability,
    ai_task_runner,
    claude_answer_cache,
    claude_approved,
    claude_spend,
    division_text,
    local_engine_bar,
    model_transport,
    reader_transport,
    subject_scope,
)
from app.config import Settings, settings
from tests.test_141_division_scope import (
    GENERAL,
    LIMITED,
    LIMITED_TT,
    NOT_GRAPHITE,
    NOT_LIMITED,
    PAGES,
    SPECIAL,
    STEEL,
    TITAN,
    TT_SCOPE,
    ZZ_SCOPE,
)

STEP = division_text.CLAUDE_STEP


def _reply_to(prompt: str) -> dict:
    if "\nSTATED:\n" in prompt:
        return NOT_GRAPHITE
    if '"titles"' in prompt:
        return {"titles": []}
    if ZZ_SCOPE in prompt:
        return LIMITED
    if TT_SCOPE in prompt:
        return LIMITED_TT
    return NOT_LIMITED


def _prompt(body: dict) -> str:
    return str(body["messages"][0]["content"])


@pytest.fixture
def send():
    def fake(url, *, headers, body, timeout):
        fake.bodies.append(body)
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": fake.wrap(json.dumps(_reply_to(_prompt(body)))),
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    fake.bodies = []
    fake.wrap = lambda text: text
    fake.usage = {}
    return fake


@pytest.fixture
def engine_calls(monkeypatch):
    calls = []

    def raising(path, *a, **k):
        calls.append(path)
        raise AssertionError(f"the local engine was reached: {path}")

    for name in ("post_json", "post_json_retrying", "stream_json", "get_json"):
        monkeypatch.setattr(model_transport, name, raising)
    monkeypatch.setattr(ai_task_runner, "_tags_cache", {})
    monkeypatch.setattr(ai_task_runner, "_IDENTITY_MEMO", {})
    return calls


@pytest.fixture(autouse=True)
def lane(tmp_path, monkeypatch, send):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "ai_division_scope_engine", "claude")
    monkeypatch.setattr(settings, "ai_division_scope_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "claude_cache")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(subject_scope, "standard_pages", lambda sid: PAGES)
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    return monkeypatch


def _gate():
    return ai_applicability.division_gate_for_run(
        [dict(r) for r in (GENERAL, SPECIAL, TITAN)],
        {"equipment_type": "Pressure vessel"},
        STEEL,
        {"std": "XYZ code"},
    )


def _ids(rows):
    return sorted(r.get("id") or r["requirement"]["id"] for r in rows)


# ------------------------------------------------------------------- the setting


def test_the_engine_is_local_by_default_and_is_in_the_config_version(monkeypatch):
    from app.config import ANSWER_AFFECTING_SETTINGS

    monkeypatch.delenv("AI_DIVISION_SCOPE_ENGINE", raising=False)
    assert Settings.model_fields["ai_division_scope_engine"].default == "ollama"
    assert "ai_division_scope_engine" in ANSWER_AFFECTING_SETTINGS


# ------------------------------------------------------------------- setting on


def test_with_the_setting_on_no_rule_is_held_for_lack_of_the_local_engine(
    send, engine_calls
):
    with local_engine_bar.bar():
        out = _gate()
        assert local_engine_bar.stated() == []
    summary = out["summary"]
    assert engine_calls == []
    assert send.bodies, "Claude was not asked"
    assert summary["could_not_read"] == 0 and summary["read"] > 0
    assert (
        "stopped" not in summary and "requirements_held_scope_not_read" not in summary
    )
    assert "aa" in _ids(out["kept"])
    assert {b["model"] for b in send.bodies} == {settings.claude_reasoning_model}


def test_every_call_is_on_one_step_under_the_ledger(send):
    _gate()
    lines = [e for e in claude_spend.entries() if e.get("settles")]
    assert len(lines) == len(send.bodies) and {e["step"] for e in lines} == {STEP}
    assert claude_spend.spent(STEP) > 0


def test_only_the_passage_is_sent_never_the_whole_standard(send):
    _gate()
    for body in send.bodies:
        prompt = _prompt(body)
        assert not (ZZ_SCOPE in prompt and TT_SCOPE in prompt)
    assert not any(
        "Titanium welds" in _prompt(b) and ZZ_SCOPE in _prompt(b) for b in send.bodies
    )


def test_a_repeat_run_is_answered_from_the_cache_at_no_cost(send):
    first = _gate()
    asked, paid = len(send.bodies), claude_spend.spent()
    second = _gate()
    assert len(send.bodies) == asked and claude_spend.spent() == paid
    assert _ids(second["kept"]) == _ids(first["kept"])
    report = claude_spend.cache_report()
    assert report["hits"] == asked


def test_a_stored_answer_is_only_in_the_gated_store_not_the_task_table(send):
    """The task table has no approved-list gate: a Claude answer must not be kept there."""
    _gate()
    assert list(claude_answer_cache._root().rglob("*.json"))
    rows = (
        ai_task_runner.connect()
        .execute("SELECT COUNT(*) FROM ai_task_cache")
        .fetchone()[0]
    )
    assert rows == 0


def test_a_fenced_reply_reads_as_the_answer(send):
    send.wrap = lambda text: f"```json\n{text}\n```"
    out = _gate()
    assert out["summary"]["could_not_read"] == 0


# ------------------------------------------------------------------- setting off


def test_with_the_setting_off_nothing_goes_to_claude_and_the_skip_counts_every_part(
    send, engine_calls, monkeypatch
):
    monkeypatch.setattr(settings, "ai_division_scope_engine", "ollama")
    with local_engine_bar.bar():
        out = _gate()
        stated = local_engine_bar.stated()
    assert send.bodies == [] and engine_calls == []
    unread = out["summary"]["could_not_read"]
    assert unread == 3 and out["summary"]["requirements_held_scope_not_read"] == 3
    assert stated == [
        {
            "step": "ai_task:division_scope",
            "calls_not_made": unread,
            "note": local_engine_bar.NOTE,
        }
    ]
    assert out["kept"] == []


def test_the_provider_switch_on_ollama_wins_over_the_setting(send, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert division_text.claude_reader() is None
    assert send.bodies == []


def test_with_egress_off_claude_is_not_used(send, monkeypatch):
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", False)
    assert division_text.claude_reader() is None


def test_an_unapproved_document_gets_no_claude_reader(monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids, "aaa")
    )
    monkeypatch.setattr(claude_approved, "_blocked_ids", lambda hashes: frozenset())
    with claude_approved.carrying(["std"]):
        assert division_text.claude_reader() is None


def test_a_blocked_document_gets_no_claude_reader_even_with_the_guard_off(monkeypatch):
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids, "aaa")
    )
    monkeypatch.setattr(
        claude_approved, "_blocked_ids", lambda hashes: frozenset(hashes)
    )
    with claude_approved.carrying(["std"]):
        assert division_text.claude_reader() is None


# ------------------------------------------------------------------- a failed call


def test_a_failed_call_holds_the_rules_says_so_and_is_charged(lane):
    calls = []

    def fails(url, *, headers, body, timeout):
        calls.append(body)
        raise httpx.ReadTimeout("late")

    lane.setattr(reader_transport, "transport", lambda: fails)
    out = _gate()
    summary = out["summary"]
    assert len(calls) == 1, "a model that stopped answering was asked again"
    assert out["kept"] == [] and sorted(
        r["requirement"]["id"] for r in out["held"]
    ) == [
        "aa",
        "tt",
        "zz",
    ]
    assert summary["requirements_held_scope_not_read"] == 3 and summary["stopped"]
    assert claude_spend.spent(STEP) > 0, (
        "a call that may have been billed was not charged"
    )


def test_a_usd_cap_holds_the_rules_and_sends_nothing(send, monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0000001)
    out = _gate()
    assert send.bodies == []
    assert out["kept"] == [] and out["summary"]["requirements_held_scope_not_read"] == 3
    assert "BudgetExceeded" in out["summary"]["stopped"]


def test_an_invalid_reply_holds_that_part_and_is_never_asked_twice(send):
    send.wrap = lambda text: "not json at all"
    out = _gate()
    assert out["summary"]["could_not_read"] == 3
    assert len(send.bodies) == 3, "a repeat read on the Claude lane costs money (#1288)"
    assert out["kept"] == []


def test_no_document_text_reaches_the_log(send, caplog):
    with caplog.at_level("DEBUG"):
        _gate()
    assert ZZ_SCOPE not in caplog.text and TT_SCOPE not in caplog.text
    assert ZZ_SCOPE not in settings.claude_spend_log.read_text("utf-8")
