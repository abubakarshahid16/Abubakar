"""Order 306.1, RETIRED 26 Nov 2026 (lead-4): the switch `tested_cards_decide_enabled` that let a tested relief-valve card decide
is gone with its OFF behaviour, and so is `card_trust` (which cards might decide): every checklist result is held for the engineer
with the rule's own verdict kept, and a run stored before then keeps its TESTED_CARD words. Invented values."""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import rule_trust
from app.config import settings
from tests.test_746_relief_valve_checklist import SHEET, fact, results


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)


def _labelled(facts=SHEET):
    return {k: rule_trust.label_check(v) for k, v in results(facts).items()}


def test_a_tested_card_no_longer_decides_it_is_held_for_the_engineer():
    r = _labelled()["PSV-24"]  # set pressure at most MAWP: 10 <= 12
    assert (
        r["trust_label"] == rule_trust.UNPROVEN
    )  # was TESTED_CARD: the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)
    assert r["status"] == "NEEDS_ENGINEER_REVIEW"  # was COMPLIANT, for the same reason
    assert (
        r["rule_said"] == "COMPLIANT"
    )  # the rule's own verdict is kept for the engineer


def test_a_breach_by_a_tested_card_is_held_with_the_rules_verdict():
    over = [f for f in SHEET if f["field_name"] != "max allow working pressure"] + [
        fact("max allow working pressure", "9.5", "barg")
    ]
    r = _labelled(over)["PSV-24"]
    assert (
        r["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # was NON_COMPLIANT: the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)
    assert (
        r["rule_said"] == "NON_COMPLIANT"
    )  # the breach is still found, as the rule's own verdict


def test_a_held_card_is_never_offered_as_an_engineers_tick():
    r = _labelled()["PSV-24"]
    assert (
        r["show_for_engineer_tick"] is False
    )  # was True for a safety field: the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)


def test_the_switch_is_gone():
    assert not hasattr(
        settings, "tested_cards_decide_enabled"
    )  # the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)


def test_with_automatic_use_off_the_hook_is_not_called(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", False)
    r = results(SHEET)["PSV-24"]
    assert (
        rule_trust.label_check(r) is r
    )  # the check comes back unchanged, no label at all


def test_the_crs_words_say_tested_never_proven_on_the_whole_path(monkeypatch):
    """cloud-2 (#1446): the words the CRS prints come from the STORED label, so the stored label must carry them."""
    from app import crs_mapping, datasheet_checks, review

    written = []
    monkeypatch.setattr(review, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(
        review,
        "create",
        lambda row, created_by=None: written.append(row) or {"id": "x", **row},
    )
    res = [r for r in results(SHEET).values() if r["rule_id"] == "PSV-24"]
    datasheet_checks.store(
        "run", "sub", res, pages_read={1: "read"}, label=rule_trust.label_check
    )
    stored = next(w for w in written if "PSV-24" in w["requirement_source_text"])
    assert (
        stored["trust_label"] == rule_trust.UNPROVEN
    )  # was TESTED_CARD: the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)
    old = {
        **stored,
        "trust_label": rule_trust.TESTED_CARD,
    }  # a row stored before the retirement keeps its words
    words = crs_mapping.trust_words(old)
    assert (
        "tested rule, engineer approval pending" in words and "proven rule" not in words
    )
    assert "proven" not in crs_mapping.safety_tick_text(
        {**old, "compliance_status": "COMPLIANT"}
    )


def test_no_card_id_is_used_twice():
    """A checklist card id is used once: a duplicate would silently hide a card (planner 03:04)."""
    ids = [
        i["id"]
        for checklist in dc.load_rules()["checklists"].values()
        if isinstance(checklist, dict)
        for i in checklist["items"]
    ]
    assert len(ids) == len(set(ids))
