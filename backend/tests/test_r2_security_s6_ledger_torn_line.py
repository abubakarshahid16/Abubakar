"""r2 S6 / B-9: a torn or invalid spend-ledger line used to be skipped, which
silently dropped what it recorded and could lift the USD cap. It now counts
conservatively (at the total cap: nothing more is spent until a person looks),
and an append never glues a new line onto an unterminated one. The caps are
untouched. Mutations: scripts/mutations/r2_security.py M1987.
"""

from __future__ import annotations

import json

import pytest

from app import claude_spend
from app.config import settings


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    return tmp_path / "spend.jsonl"


def _line(step: str, usd: float) -> str:
    return json.dumps({"step": step, "cost_usd": usd}) + "\n"


def test_a_torn_line_is_not_nothing_spent(_ledger):
    _ledger.write_text(_line("recheck", 4.0) + '{"step": "recheck", "cost_usd": 4.', encoding="utf-8")
    assert claude_spend.spent() >= 20.0, "a torn line was skipped, so the cap was lifted"
    with pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.reserve("recheck", 0.01, model="claude-sonnet-5")


def test_an_invalid_line_in_the_middle_fails_closed(_ledger):
    _ledger.write_text(_line("a", 1.0) + "not json at all\n" + _line("a", 1.0), encoding="utf-8")
    with pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.reserve("a", 0.01, model="claude-sonnet-5")


def test_a_valid_ledger_is_unchanged_and_the_caps_are_the_same(_ledger):
    _ledger.write_text(_line("a", 1.0) + _line("b", 2.0), encoding="utf-8")
    assert claude_spend.spent() == 3.0
    held = claude_spend.reserve("a", 1.0, model="claude-sonnet-5")
    assert held.worst_usd == 1.0
    with pytest.raises(claude_spend.BudgetExceeded):          # step cap still 5
        claude_spend.reserve("a", 4.5, model="claude-sonnet-5")


def test_an_append_after_an_unterminated_line_starts_a_new_line(_ledger):
    _ledger.write_text(_line("a", 1.0).rstrip("\n"), encoding="utf-8")   # no trailing newline
    claude_spend.record(step="b", model="claude-sonnet-5", usage={"input_tokens": 10},
                        prompt_sha256="x", wall_time_s=0.0, finish_reason="ok")
    lines = _ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(x)["step"] for x in lines] == ["a", "b"], \
        "the new entry was glued onto the unterminated line, corrupting both"
    assert all(e.get("corrupt") is not True for e in claude_spend.entries())
