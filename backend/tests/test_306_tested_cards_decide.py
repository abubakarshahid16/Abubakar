"""Order 306.1: a relief-valve card tested under the stricter rule may decide while its engineer approval is
pending, behind `tested_cards_decide_enabled`. Every other card stays held for the engineer. Invented values."""

from __future__ import annotations

import pytest

from app import card_trust, rule_cards, rule_trust
from app import datasheet_checks as dc
from app.config import settings
from tests.test_746_relief_valve_checklist import PSV, SHEET, fact, results


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)
    card_trust.clear()
    yield
    card_trust.clear()


def _labelled(facts=SHEET):
    return {k: rule_trust.label_check(v) for k, v in results(facts).items()}


def test_a_tested_card_with_written_cases_decides_and_says_what_it_rests_on():
    r = _labelled()["PSV-24"]  # set pressure at most MAWP: 10 <= 12
    assert r["status"] == "COMPLIANT" and r["trust_label"] == rule_trust.TESTED_CARD
    assert r["trust_words"] == "automatic (tested rule, engineer approval pending)"
    assert r["trust_label"] != rule_trust.AUTO_PROVEN  # never a proven family
    assert not r.get("rule_said")


def test_a_breach_by_a_tested_card_is_a_verdict_too():
    over = [f for f in SHEET if f["field_name"] != "max allow working pressure"] + [
        fact("max allow working pressure", "9.5", "barg")
    ]
    r = _labelled(over)["PSV-24"]
    assert r["status"] == "NON_COMPLIANT" and r["trust_label"] == rule_trust.TESTED_CARD


def test_a_compliant_verdict_on_a_safety_field_goes_to_the_engineers_tick():
    r = _labelled()["PSV-24"]
    assert r["tier"] == rule_trust.SAFETY and r["show_for_engineer_tick"] is True
    non_safety = next(
        k
        for k in _labelled()
        if card_trust.why_not(k) is None and not card_trust.safety(k)
    )
    assert _labelled()[non_safety]["show_for_engineer_tick"] is False


def test_a_card_with_generated_cases_only_stays_held():
    r = _labelled()[
        "PSV-01"
    ]  # "the set pressure is stated": tested by generated cases only
    assert card_trust.why_not("PSV-01") == "generated cases only"
    assert r["trust_label"] == rule_trust.UNPROVEN
    assert r["status"] == "NEEDS_ENGINEER_REVIEW" and r["rule_said"] == "COMPLIANT"


@pytest.mark.parametrize(
    "card, why",
    [
        ("PSV-03", "weak source"),
        ("PSV-15", "weak source"),
        ("PSV-05", "a standard we do not hold"),
    ],
)
def test_a_weak_or_waiting_card_stays_held(card, why):
    assert why in card_trust.why_not(card)
    got = _labelled()
    if card in got:
        assert got[card]["trust_label"] == rule_trust.UNPROVEN


def test_a_card_whose_tests_fail_stays_held(monkeypatch):
    real = rule_cards.run_card
    monkeypatch.setattr(
        rule_cards,
        "run_card",
        lambda item, t, rules=None: {
            **real(item, t, rules),
            "status": "draft",
            "why": "a case failed",
        },
    )
    card_trust.clear()
    assert card_trust.why_not("PSV-24") == "a case failed"
    assert _labelled()["PSV-24"]["trust_label"] == rule_trust.UNPROVEN


def test_a_source_that_is_not_a_clause_number_stays_held(monkeypatch):
    card_trust.clear()
    _, item = card_trust._cards()["PSV-24"]
    monkeypatch.setitem(item["source"], "clause", "datasheet fields")
    card_trust.why_not.cache_clear()
    assert card_trust.why_not("PSV-24") == "the source is not a clause number"


def test_only_the_relief_valve_cards_decide_for_now():
    vessel = dc.load_rules()["checklists"]["Pressure Vessel"]["items"][0]["id"]
    assert card_trust.why_not(vessel) == "this equipment type's cards do not decide yet"


def test_a_local_item_never_decides():
    assert not card_trust.decides(
        {"checklist": True, "local": True, "rule_id": "PSV-24"}
    )
    assert not card_trust.decides({"checklist": False, "rule_id": "PSV-24"})
    assert not card_trust.decides({"checklist": True, "rule_id": "NO-SUCH"})


def test_with_the_switch_off_nothing_changes(monkeypatch):
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", False)
    r = _labelled()["PSV-24"]
    assert (
        r["trust_label"] == rule_trust.UNPROVEN
        and r["status"] == "NEEDS_ENGINEER_REVIEW"
    )
    assert r["rule_said"] == "COMPLIANT"


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
    assert stored["trust_label"] == rule_trust.TESTED_CARD
    words = crs_mapping.trust_words(stored)
    assert (
        "tested rule, engineer approval pending" in words and "proven rule" not in words
    )
    assert "proven" not in crs_mapping.safety_tick_text(
        {**stored, "compliance_status": "COMPLIANT"}
    )


def test_a_sizing_calculation_card_never_decides():
    """Planner 03:04: the four calc cards have no at-the-limit case, so they stay held whatever their cases say."""
    calc = [
        i["id"]
        for i in dc.load_rules()["checklists"][PSV]["items"]
        if i["rule"]["kind"] == "calc"
    ]
    assert len(calc) == 4
    for card_id in calc:
        assert card_trust.why_not(card_id) == "a sizing calculation does not decide yet"
    assert [
        k
        for k in _labelled()
        if k in calc and _labelled()[k]["trust_label"] == rule_trust.TESTED_CARD
    ] == []


def test_the_cards_that_decide_all_have_an_at_the_limit_case_or_need_none():
    for card_id, (equipment_type, item) in card_trust._cards().items():
        if (
            card_trust.why_not(card_id) is None
            and item["rule"]["kind"] in rule_cards.BOUNDARY_KINDS
        ):
            names = {
                r["case"] for r in rule_cards.run_card(item, equipment_type)["runs"]
            }
            assert "at the limit" in names, card_id


def test_no_card_id_is_used_twice():
    """`card_trust._cards` is keyed by id: a duplicate would silently hide a card (planner 03:04)."""
    ids = [
        i["id"]
        for checklist in dc.load_rules()["checklists"].values()
        if isinstance(checklist, dict)
        for i in checklist["items"]
    ]
    assert len(ids) == len(set(ids))
