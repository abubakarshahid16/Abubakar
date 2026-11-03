"""Item 14: the run record and the held-sheet reason name the real tier of an engineer-approved rule. Invented rows."""

from __future__ import annotations

from app import rule_trust

CODES = ("A", "B", "C", "D")


def row(label, status="NON_COMPLIANT", tick=False):
    return {
        "trust_label": label,
        "compliance_status": status,
        "show_for_engineer_tick": tick,
    }


def test_two_engineer_approved_decisions_are_counted_as_the_engineers():
    rows = [
        row(rule_trust.ENGINEER_APPROVED),
        row(rule_trust.ENGINEER_APPROVED, "COMPLIANT"),
    ]
    tiers = rule_trust.decided_by_tier(rows)["decided_by_tier"]
    assert tiers["engineer_approved"] == 2
    assert tiers["owner_approved"] == 0


def test_a_run_with_only_engineer_approved_rules_still_gets_a_tier_record():
    assert rule_trust.decided_by_tier([row(rule_trust.ENGINEER_APPROVED)])
    assert rule_trust.decided_by_tier([row(rule_trust.UNPROVEN)]) == {}


def test_an_engineer_approved_safety_pass_waits_for_its_tick_apart_from_the_decided():
    rows = [
        row(rule_trust.ENGINEER_APPROVED),
        row(rule_trust.ENGINEER_APPROVED, "COMPLIANT", tick=True),
    ]
    tiers = rule_trust.decided_by_tier(rows)["decided_by_tier"]
    assert tiers["engineer_approved"] == 1
    assert tiers["engineer_approved_awaiting_tick"] == 1


def test_the_review_note_prints_the_engineer_approved_count():
    trust = rule_trust.decided_by_tier([row(rule_trust.ENGINEER_APPROVED)])
    notes = rule_trust.review_notes(
        {"rule_trust": {**trust, "findings_counted": 1}}, []
    )
    text = " ".join(n["detail"] for n in notes)
    assert "1 by engineer-approved rules" in text


def _open(label):
    return {
        "trust_label": label,
        "show_for_engineer_tick": True,
        "compliance_status": "COMPLIANT",
    }


def test_the_held_sheet_reason_names_the_real_tier():
    held = rule_trust.hold_open_ticks(
        {"code": "A", "reason": "r"}, [_open(rule_trust.ENGINEER_APPROVED)], CODES
    )
    assert "engineer-approved rule" in held["reason"]
    assert "owner-approved" not in held["reason"]
    owner = rule_trust.hold_open_ticks(
        {"code": "A", "reason": "r"}, [_open(rule_trust.OWNER_APPROVED)], CODES
    )
    assert "an owner-approved rule" in owner["reason"]
    mixed = rule_trust.hold_open_ticks(
        {"code": "A", "reason": "r"},
        [_open(rule_trust.OWNER_APPROVED), _open(rule_trust.ENGINEER_APPROVED)],
        CODES,
    )
    assert "owner- or engineer-approved" in mixed["reason"]
