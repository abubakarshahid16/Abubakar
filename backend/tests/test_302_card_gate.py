"""Order 302.4 c: the engineer's approval joins the review's card gate (switch `rule_cards_approval_enabled`).
Approved = "rule approved by <engineer>"; tested = "tested rule, engineer approval pending"; an edited, draft or
rejected card is held; the edited content is what the review evaluates. Invented values only."""

from __future__ import annotations

import pytest

from app import checklist_scope, crs_mapping, datasheet_checks, db, review, rule_trust
from app import rule_card_versions as versions
from app.config import settings
from tests.test_746_relief_valve_checklist import PSV, SHEET
from tests.test_crs_endpoint import _run, _submittal, temp_db  # noqa: F401 - fixture

CARD = "PSV-24"  # set pressure at most MAWP; a written-case card with a clause number
WHO = "engineer@example.test"


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    monkeypatch.setattr(settings, "rule_cards_approval_enabled", True)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)


def _seen():
    card = versions.current(db.connect(), PSV, CARD)
    return {"version": card["version"], "seen_hash": card["content_hash"]}


def _approve():
    versions.decide(db.connect(), PSV, CARD, versions.APPROVED, actor=WHO, **_seen())


def _labelled(facts=SHEET):
    results = checklist_scope.evaluate(facts, {"equipment_type": PSV}, {1: "x"})
    return {
        r["rule_id"]: rule_trust.label_check(r) for r in results if r.get("checklist")
    }[CARD]


def test_a_tested_card_nobody_decided_is_tested_not_approved():
    r = _labelled()
    assert r["trust_label"] == rule_trust.TESTED_CARD and r["status"] == "COMPLIANT"
    assert r["trust_words"] == "automatic (tested rule, engineer approval pending)"


def test_an_approved_card_is_the_engineers_rule_by_name():
    _approve()
    r = _labelled()
    assert (
        r["trust_label"] == rule_trust.ENGINEER_CONFIRMED and r["status"] == "COMPLIANT"
    )
    assert r["trust_by"] == WHO and r["trust_words"] == f"rule approved by {WHO}"
    assert not r.get("rule_said")


def test_an_edit_takes_the_approval_away_and_the_edit_is_what_is_evaluated():
    _approve()
    versions.edit(db.connect(), PSV, CARD, {"op": ">="}, actor=WHO, **_seen())
    r = _labelled()  # now "set pressure at least MAWP": 10 vs 12 fails, and the card fails its own tests
    assert r["status"] == "NEEDS_ENGINEER_REVIEW" and r["rule_said"] == "NON_COMPLIANT"
    assert r["trust_label"] == rule_trust.UNPROVEN and "trust_by" not in r


def test_an_edit_that_still_passes_its_tests_is_tested_not_approved():
    _approve()
    versions.edit(db.connect(), PSV, CARD, {"severity": "minor"}, actor=WHO, **_seen())
    r = _labelled()
    assert r["trust_label"] == rule_trust.TESTED_CARD and "trust_by" not in r
    assert r["severity"] == "minor"  # the edited content is the one in force


def test_a_rejected_card_is_held_for_the_engineer():
    versions.decide(db.connect(), PSV, CARD, versions.REJECTED, actor=WHO, **_seen())
    r = _labelled()
    assert r["trust_label"] == rule_trust.UNPROVEN
    assert r["status"] == "NEEDS_ENGINEER_REVIEW" and r["rule_said"] == "COMPLIANT"


def test_a_tested_card_is_held_when_tested_cards_may_not_decide(monkeypatch):
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", False)
    assert _labelled()["trust_label"] == rule_trust.UNPROVEN


def test_an_approved_card_decides_even_with_tested_cards_off(monkeypatch):
    """The engineer's approval does not depend on the tested-card switch."""
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", False)
    _approve()
    assert _labelled()["trust_label"] == rule_trust.ENGINEER_CONFIRMED


def test_with_the_approval_switch_off_the_approval_is_ignored(monkeypatch):
    _approve()
    monkeypatch.setattr(settings, "rule_cards_approval_enabled", False)
    r = _labelled()
    assert r["trust_label"] == rule_trust.TESTED_CARD and "trust_by" not in r


def test_the_crs_says_approved_by_name_never_proven_or_tested():
    """Whole path with the real store: a finding stored from an approved card keeps the engineer's name, and the
    CRS words are built from the STORED finding."""
    _approve()
    doc = _submittal()
    run = _run(doc)
    res = [
        r
        for r in checklist_scope.evaluate(SHEET, {"equipment_type": PSV}, {1: "x"})
        if r.get("rule_id") == CARD
    ]
    datasheet_checks.store(
        run, doc, res, pages_read={1: "read"}, label=rule_trust.label_check
    )
    stored = review.list_findings(review_run_id=run)[0]
    assert (
        stored["trust_label"] == rule_trust.ENGINEER_CONFIRMED
        and stored["trust_by"] == WHO
    )
    assert crs_mapping.trust_words(stored) == f"rule approved by {WHO}"
    assert "proven" not in crs_mapping.trust_words(stored)


def test_an_engineer_confirmed_finding_without_a_name_keeps_the_old_words():
    assert (
        crs_mapping.trust_words({"trust_label": rule_trust.ENGINEER_CONFIRMED})
        == "engineer-approved rule"
    )


def test_the_finding_table_keeps_the_engineers_name():
    review.ensure_schema()
    columns = {
        r["name"] for r in db.connect().execute("PRAGMA table_info(review_findings)")
    }
    assert "trust_by" in columns


def test_a_sizing_calculation_card_cannot_be_approved():
    """cloud-2 (#1456): an approval cannot make the review decide what it is not built to decide."""
    calc = next(
        i["id"]
        for i in datasheet_checks.load_rules()["checklists"][PSV]["items"]
        if i["rule"]["kind"] == "calc"
    )
    seen = versions.current(db.connect(), PSV, calc)
    with pytest.raises(
        versions.CardError, match="can be rejected or edited, not approved"
    ):
        versions.decide(
            db.connect(),
            PSV,
            calc,
            versions.APPROVED,
            version=seen["version"],
            seen_hash=seen["content_hash"],
            actor=WHO,
        )


def test_a_stored_approval_on_a_card_the_review_cannot_decide_is_held(monkeypatch):
    """An approval given before the rule existed still gives no verdict."""
    from app import card_trust

    calc = next(
        i["id"]
        for i in datasheet_checks.load_rules()["checklists"][PSV]["items"]
        if i["rule"]["kind"] == "calc"
    )
    monkeypatch.setattr(
        card_trust,
        "standing",
        lambda rule_id: {
            "state": "approved",
            "decided_by": WHO,
            "reason": None,
            "structural": "a sizing calculation does not decide yet",
        },
    )
    assert (
        card_trust.label_for({"checklist": True, "rule_id": calc})
        == rule_trust.UNPROVEN
    )
