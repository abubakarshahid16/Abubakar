"""The "not included in this analysis" market line follows the settings that
decide it (review finding, 2026-10-02): it said "this machine is offline" in
four API responses whether or not egress was switched on.
"""
from __future__ import annotations

import pytest

from app import analysis
from app.config import settings


def _market_line(monkeypatch, live: bool, egress: bool) -> str:
    monkeypatch.setattr(settings, "market_live_enabled", live)
    monkeypatch.setattr(settings, "market_allow_public_egress", egress)
    lines = [s for s in analysis.not_implemented_sections() if "market" in s]
    assert len(lines) == 1
    return lines[0]


def test_everything_off_says_switched_off_and_never_offline(monkeypatch):
    line = _market_line(monkeypatch, False, False)
    assert "switched off" in line
    assert "offline" not in line


def test_switched_on_but_egress_not_allowed_says_so(monkeypatch):
    line = _market_line(monkeypatch, True, False)
    assert "does not allow traffic to leave" in line
    assert "offline" not in line


def test_switched_on_and_allowed_does_not_claim_the_machine_is_offline(monkeypatch):
    """THE MUTATION TARGET: the literal that used to be here cannot come back."""
    line = _market_line(monkeypatch, True, True)
    assert "offline" not in line and "runs only when a search is approved" in line


@pytest.mark.parametrize("live,egress", [(False, False), (True, False), (True, True)])
def test_the_other_gaps_are_still_named(monkeypatch, live, egress):
    _market_line(monkeypatch, live, egress)
    text = " ".join(analysis.not_implemented_sections())
    assert "revision" in text and "cancellation" in text
