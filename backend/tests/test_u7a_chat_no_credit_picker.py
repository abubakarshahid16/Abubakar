"""Chat's engine picker (planner's live 7a check, 26 Nov 2026): while the last Claude call was refused for no credit and nothing has
succeeded since, Claude is shown as unavailable with the no-credit sentence, before anyone sends. The same rule as the review
plan's note (M4): a later success clears it at once. Invented ledger lines only; no call is made."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app import aim_review_gate, chat_model, claude_spend
from app.config import settings

REFUSED = {
    "releases": "r1",
    "step": "chat",
    "reason": f"unbilled:HTTPStatusError:http_400:{claude_spend.NO_CREDIT}",
}
SUCCESS = {"settles": "r2", "step": "chat", "finish_reason": "end_turn", "usd": 0.01}


def _at(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds"
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "spend.jsonl"
    monkeypatch.setattr(settings, "claude_spend_log", path)

    def write(*lines):
        path.write_text(
            "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
        )

    return write


@pytest.fixture
def lane_open(monkeypatch):
    monkeypatch.setattr(chat_model, "_gate", lambda: (None, "claude"))


def _claude(models: dict) -> dict:
    return next(m for m in models["models"] if m["id"] == chat_model.CLAUDE)


def test_after_a_credit_refusal_claude_is_unavailable_in_the_picker_with_the_no_credit_sentence(
    ledger, lane_open
):
    ledger({**REFUSED, "at": _at(5)})
    got = chat_model.available_models()
    assert _claude(got)["available"] is False
    assert _claude(got)["reason"] == aim_review_gate.NO_CREDIT_WORDS
    assert got["default"] == chat_model.LOCAL


def test_a_later_success_clears_it_at_once(ledger, lane_open):
    ledger(
        {**REFUSED, "at": _at(10)}, {**SUCCESS, "at": _at(2)}
    )  # inside the window: the success clears it
    assert _claude(chat_model.available_models())["available"] is True


# Each case's lines are built WHEN THE TEST RUNS, not when the module is collected: "10 minutes ago" taken at collection time
# is past the 15-minute mark by the time a long suite reaches this test (CI shard 3, update 12), and a refusal that should
# count no longer does. The cases' meaning is unchanged.
@pytest.mark.parametrize(
    "make_lines, refused",
    [
        (
            lambda: [{**REFUSED, "at": _at(chat_model.CREDIT_REFUSAL_MINUTES + 1)}],
            False,
        ),  # older than the window: Claude offered again
        (
            lambda: [{**REFUSED, "at": _at(10)}, {"cached": True, "at": _at(5)}],
            True,
        ),  # a cache hit proves nothing about credit
        (
            lambda: [{**REFUSED, "at": _at(10)}, {"reserves": "r3", "at": _at(5)}],
            True,
        ),  # a call only reserved proves nothing
        (
            lambda: [
                {**SUCCESS, "at": _at(10)},
                {
                    **REFUSED,
                    "finish_reason": f"failed:x:http_400:{claude_spend.NO_CREDIT}",
                    "reason": None,
                    "settles": "r4",
                    "at": _at(5),
                },
            ],
            True,
        ),  # a charged failure for no credit counts too
        (lambda: [], False),
    ],
    ids=["older_than_window", "cache_hit", "only_reserved", "charged_failure", "empty"],
)
def test_the_rule_reads_the_latest_outcome_of_the_last_day(ledger, make_lines, refused):
    ledger(*make_lines())
    assert chat_model.credit_refused_now() is refused


def test_an_unreadable_ledger_never_hides_claude(ledger, lane_open, monkeypatch):
    def broken():
        raise OSError("invented")

    monkeypatch.setattr(claude_spend, "_raw_lines", broken)
    assert _claude(chat_model.available_models())["available"] is True


def test_after_a_top_up_the_picker_offers_claude_again_within_the_window(
    ledger, lane_open
):
    """Review of update 12, N6: Chat cannot make the call that would clear the mark, so the mark lasts only
    `CREDIT_REFUSAL_MINUTES`: a refusal just inside it hides Claude; just past it, Claude is offered again."""
    assert chat_model.CREDIT_REFUSAL_MINUTES <= 15
    ledger({**REFUSED, "at": _at(chat_model.CREDIT_REFUSAL_MINUTES - 1)})
    assert _claude(chat_model.available_models())["available"] is False
    ledger({**REFUSED, "at": _at(chat_model.CREDIT_REFUSAL_MINUTES + 1)})
    assert _claude(chat_model.available_models())["available"] is True
