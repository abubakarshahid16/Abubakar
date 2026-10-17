"""#482: the chat names the outbound lanes that are on, instead of always
promising "Nothing you type leaves this machine".

WHAT WAS WRONG. `intent._REPLIES` answered "what can you do" and "bye" with a
fixed promise that nothing leaves the machine, whatever `.env` said - so with
the Claude lane open (both egress flags and a key) the chat still promised it.
Now the promise is made only when every lane is off; otherwise the lanes are
named.
"""
from __future__ import annotations

import pytest

from app import intent
from app.config import settings


@pytest.fixture
def all_off(monkeypatch):
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
                 "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"standards_reader_enabled": False,
                        "standards_reader_allow_public_egress": False,
                        "anthropic_api_key": "", "market_live_enabled": False,
                        "market_allow_public_egress": False, "smtp_enabled": False}.items():
        monkeypatch.setattr(settings, name, value)
    return monkeypatch


def _claude_on(mp):
    mp.setattr(settings, "standards_reader_enabled", True)
    mp.setattr(settings, "standards_reader_allow_public_egress", True)
    mp.setattr(settings, "anthropic_api_key", "sk-test-not-real")


def test_with_every_lane_off_the_promise_is_made(all_off):
    assert intent.outbound_lanes() == []
    for kind in ("about_the_assistant", "farewell"):
        assert intent.guidance(kind).endswith("Nothing you type leaves this machine.")


def test_with_the_claude_lane_open_it_is_named_and_nothing_is_promised(all_off):
    _claude_on(all_off)
    for kind in ("about_the_assistant", "farewell"):
        reply = intent.guidance(kind)
        assert "the Claude API" in reply
        assert "Nothing you type leaves this machine" not in reply


def test_every_lane_that_is_on_is_named(all_off):
    _claude_on(all_off)
    all_off.setattr(settings, "market_live_enabled", True)
    all_off.setattr(settings, "market_allow_public_egress", True)
    all_off.setattr(settings, "smtp_enabled", True)
    assert intent.outbound_lanes() == ["the Claude API", "market search", "email notifications"]


def test_half_a_lane_is_not_a_lane(all_off):
    """One egress flag without the other, or flags without a key, opens nothing -
    so the reply must still say nothing leaves (the gates' own rule)."""
    all_off.setattr(settings, "standards_reader_enabled", True)
    all_off.setattr(settings, "market_live_enabled", True)
    assert intent.outbound_lanes() == []
