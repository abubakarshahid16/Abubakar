"""Item 14: the label an approval earns in `rule_trust`. Invented approvals only."""

from __future__ import annotations

from app import rule_trust
from app.config import settings

SIGNED = {"by": "user-1", "at": "2026-11-03T08:00:00+00:00"}


def _on(monkeypatch, engineer=True):
    monkeypatch.setattr(settings, "owner_approved_rules_decide_enabled", True)
    monkeypatch.setattr(settings, "engineer_approved_rules_decide_enabled", engineer)
    monkeypatch.setattr(rule_trust, "second_check", lambda rule: (True, None))


def test_an_engineer_approval_earns_the_engineer_label_never_the_owners(monkeypatch):
    _on(monkeypatch)
    label = rule_trust.tier_for_approved({**SIGNED, "tier": "engineer"}, {})
    assert label == rule_trust.ENGINEER_APPROVED
    assert label != rule_trust.OWNER_APPROVED
    owner = rule_trust.tier_for_approved({**SIGNED, "tier": "owner"}, {})
    assert owner == rule_trust.OWNER_APPROVED


def test_an_engineer_approval_earns_nothing_with_its_switch_off(monkeypatch):
    _on(monkeypatch, engineer=False)
    got = rule_trust.tier_for_approved({**SIGNED, "tier": "engineer"}, {})
    assert got == rule_trust.UNPROVEN


def test_an_unsigned_or_unknown_tier_earns_nothing(monkeypatch):
    _on(monkeypatch)
    assert rule_trust.tier_for_approved({"tier": "engineer"}, {}) == rule_trust.UNPROVEN
    assert (
        rule_trust.tier_for_approved({**SIGNED, "tier": "draft"}, {})
        == rule_trust.UNPROVEN
    )
    assert rule_trust.tier_for_approved(None, {}) == rule_trust.UNPROVEN
