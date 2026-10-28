"""Order 271.3 (owner, #805 plan change 4): the Claude spend caps for November. The total is USD 500, one
standard's conversion is capped at USD 25 (`standards_convert:<standard>`), every other step keeps USD 5.
A call over a cap is refused BEFORE it leaves, and the converter stops cleanly there."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app import claude_spend, db, standards_converter
from app.config import settings
from app.reasoning_provider import ClaudeProvider
from tests.test_270_standards_converter import (  # noqa: F401 - the fixture is autouse here
    PUMP,
    _standard,
    temp_db,
)
from tests.test_chat_pr1_model_lane import KEY

MODEL = "claude-sonnet-5"
ONE = "standards_convert:SAES-G-005"
TWO = "standards_convert:ISO 15156-3"


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(standards_converter, "ASK_TWICE", False)  # these test the first pass (305.4 has its own file)
    # the USD 500 is for November 2026: these tests run on a November day whatever day it is
    monkeypatch.setattr(claude_spend, "_today", lambda: date(2026, 11, 15))


def _hold(step: str, usd: float):
    return claude_spend.reserve(step, usd, model=MODEL)


def test_the_code_defaults_are_the_owners_numbers():
    assert settings.claude_budget_usd_total == 500.0
    assert settings.claude_budget_usd_per_standard == 25.0
    assert settings.claude_budget_usd_per_step == 5.0


def test_one_standards_conversion_may_spend_up_to_25_and_not_a_cent_more():
    _hold(ONE, 24.0)
    _hold(ONE, 1.0)  # 25.00 exactly fits
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$25\.00 per step"):
        _hold(ONE, 0.01)
    assert claude_spend.spent(ONE) == 25.0


def test_each_standard_has_its_own_25():
    _hold(ONE, 25.0)
    _hold(TWO, 25.0)
    with pytest.raises(claude_spend.BudgetExceeded):
        _hold(TWO, 0.01)


def test_every_other_step_keeps_its_5_dollar_cap():
    _hold("requirement-matcher", 4.9)
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$5\.00 per step"):
        _hold("requirement-matcher", 0.2)
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$5\.00 per step"):
        _hold(
            "standards-convert-lookalike", 5.5
        )  # only the exact prefix earns the larger cap


def test_the_total_is_500_not_20():
    _hold("requirement-matcher", 4.0)
    for n in range(19):  # 4 + 19 * 25 = 479
        _hold(f"standards_convert:S-{n}", 25.0)
    _hold("standards_convert:S-last", 21.0)  # 500.00 exactly fits
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$500\.00 in total"):
        _hold("standards_convert:S-over", 0.01)


def test_a_caller_that_passes_its_own_caps_gets_exactly_those():
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$5\.00 per step"):
        claude_spend.reserve(ONE, 10.0, model=MODEL, caps=claude_spend.Caps(5.0, 20.0))


def test_the_read_only_check_applies_the_same_per_standard_cap():
    _hold(ONE, 24.0)
    claude_spend.ensure_affordable(ONE, 1.0)
    with pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.ensure_affordable(ONE, 1.01)
    with pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.ensure_affordable("other-step", 5.01)


def test_the_converter_stops_cleanly_when_the_standards_25_is_used(
    monkeypatch, tmp_path
):
    """The real provider and the real ledger: 24.999 is already spent on this standard, so the next call's
    worst case crosses 25 and is refused before it leaves; the run is marked 'stopped at cap'."""
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    _hold(ONE, 24.999)
    sent = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        raise AssertionError("a call over the cap must not leave")

    std = _standard(texts=("The casing design pressure shall not exceed 25 bar.",))
    with db.connect() as conn:
        result = standards_converter.convert(
            conn, std, "SAES-G-005", PUMP, ClaudeProvider(MODEL, transport=send)
        )
    assert sent == [] and result.stopped_at_cap and result.refused is None
    assert [r["status"] for r in result.rows] == ["not_asked"]
    files = standards_converter.write(result, tmp_path / "mirror", form_sha="b54474a2")
    assert json.loads(files["json"].read_text())["run"] == "stopped at cap"


def test_a_standard_under_the_cap_is_asked_and_charged_to_its_own_step(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    def send(url, *, headers, body, timeout):
        return {
            "model": MODEL,
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"checks": [{"i": 0, "applies": "yes", "field": None}]}
                    ),
                }
            ],
            "usage": {"input_tokens": 1000, "output_tokens": 100},
        }

    std = _standard(texts=("Bearings shall be lubricated.",))
    with db.connect() as conn:
        result = standards_converter.convert(
            conn, std, "SAES-G-005", PUMP, ClaudeProvider(MODEL, transport=send)
        )
    assert not result.stopped_at_cap and result.refused is None and result.calls == 1
    assert [r["reason"] for r in result.rows] == ["no_field"]
    assert 0 < claude_spend.spent(
        ONE
    ) < 1 and claude_spend.spent() == claude_spend.spent(ONE)
    assert result.usd == claude_spend.spent(ONE)


# ------------------------------------------------------------------ the November window ends in code


def _day(monkeypatch, y, m, d):
    monkeypatch.setattr(claude_spend, "_today", lambda: date(y, m, d))


def test_the_500_holds_on_the_last_day_of_november_and_lapses_the_next(monkeypatch):
    _day(monkeypatch, 2026, 11, 30)
    assert (
        claude_spend.total_cap() == 500.0
        and claude_spend.Caps.from_settings().total == 500.0
    )
    _day(monkeypatch, 2026, 12, 1)
    assert (
        claude_spend.total_cap() == 20.0
        and claude_spend.Caps.from_settings().total == 20.0
    )


def test_a_lapsed_approval_cannot_be_renewed_by_a_bigger_env_value(monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_total", 1500.0)
    _day(monkeypatch, 2026, 11, 30)
    assert claude_spend.total_cap() == 1500.0
    _day(monkeypatch, 2027, 1, 5)
    assert claude_spend.total_cap() == 20.0


def test_a_total_set_below_20_stays_below_20_after_the_window(monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_total", 7.0)
    _day(monkeypatch, 2026, 12, 2)
    assert claude_spend.total_cap() == 7.0


def test_after_the_window_a_reservation_meets_the_old_20_total(monkeypatch):
    _day(monkeypatch, 2026, 12, 1)
    _hold(ONE, 20.0)
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$20\.00 in total"):
        _hold(TWO, 0.01)


def test_an_unreadable_ledger_line_counts_at_the_total_cap_in_force(
    monkeypatch, tmp_path
):
    (tmp_path / "spend.jsonl").write_text("{torn\n", encoding="utf-8")
    _day(monkeypatch, 2026, 11, 20)
    assert claude_spend.spent(claude_spend.CORRUPT_STEP) == 500.0
    _day(monkeypatch, 2026, 12, 1)
    assert claude_spend.spent(claude_spend.CORRUPT_STEP) == 20.0
