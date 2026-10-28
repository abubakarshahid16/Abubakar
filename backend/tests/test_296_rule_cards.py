"""Order 296: a rule card is tested with the REAL checking code. Invented rules only."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from app import datasheet_checks as dc

_SPEC = importlib.util.spec_from_file_location(
    "rule_cards", Path(__file__).resolve().parents[2] / "scripts" / "rule_cards.py"
)
rule_cards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rule_cards)

TYPE = "Pressure Safety Valve"
RULES = dc.load_rules()
SET_PRESSURE = {
    "id": "T-01",
    "text": "The set pressure is stated.",
    "source": {"standard": "TEST 1", "clause": "1.1"},
    "rule": {"kind": "required", "field": "set_pressure"},
    "severity": "major",
}
FLUID = {
    "id": "T-02",
    "text": "The fluid phase is one of the allowed phases.",
    "source": {"standard": "TEST 1", "clause": "1.2"},
    "rule": {"kind": "allowed", "field": "fluid_phase", "values": ["gas", "liquid"]},
    "severity": "major",
}


def _item(base: dict) -> dict:
    return copy.deepcopy(base)


def test_a_required_rule_is_tested_by_a_value_a_missing_value_and_a_placeholder():
    card = rule_cards.run_card(_item(SET_PRESSURE), TYPE, RULES)
    assert card["status"] == "tested" and card["why"] == ""
    got = {r["case"]: (r["expected"], r["got"]) for r in card["runs"]}
    assert got == {
        "meets": (dc.COMPLIANT, dc.COMPLIANT),
        "breaks": (dc.MISSING_INFORMATION, dc.MISSING_INFORMATION),
        "unclear": (dc.MISSING_INFORMATION, dc.MISSING_INFORMATION),
    }


def test_an_allowed_rule_is_tested_with_an_allowed_a_refused_and_two_different_values():
    card = rule_cards.run_card(_item(FLUID), TYPE, RULES)
    assert card["status"] == "tested"
    got = {r["case"]: r["got"] for r in card["runs"]}
    assert got == {
        "meets": dc.COMPLIANT,
        "breaks": dc.NON_COMPLIANT,
        "unclear": dc.NEEDS_ENGINEER_REVIEW,
    }


def test_a_card_whose_rule_the_code_does_not_follow_stays_draft_and_says_why(
    monkeypatch,
):
    """The runner calls the real code: if the code answers differently, the card fails (no copy of the code)."""
    real = dc.evaluate

    def always_compliant(*args, **kwargs):
        return [{**r, "status": dc.COMPLIANT} for r in real(*args, **kwargs)]

    monkeypatch.setattr(dc, "evaluate", always_compliant)
    card = rule_cards.run_card(_item(SET_PRESSURE), TYPE, RULES)
    assert card["status"] == "draft" and card["why"] == "a case failed"
    assert [r["case"] for r in card["runs"] if not r["passed"]] == ["breaks", "unclear"]


def test_a_rule_kind_with_no_generated_case_is_draft_until_a_person_writes_cases():
    item = _item(SET_PRESSURE)
    item["rule"] = {
        "kind": "compare",
        "left": "set_pressure",
        "op": "<=",
        "right": "design_pressure",
    }
    card = rule_cards.run_card(item, TYPE, RULES)
    assert (
        card["status"] == "draft"
        and card["why"] == "no test cases for this kind of rule"
    )
    assert card["runs"] == []


def test_written_cases_count_beside_the_generated_ones_and_are_marked_apart():
    item = _item(SET_PRESSURE)
    item["rule"] = {
        "kind": "compare",
        "left": "set_pressure",
        "op": "<=",
        "right": "design_pressure",
    }
    ten = rule_cards._fact("set pressure", "10")
    twelve = rule_cards._fact("design pressure", "12")
    item["tests"] = [
        {
            "name": "meets",
            "kind": "written",
            "facts": [ten, twelve],
            "text": "",
            "expect": dc.COMPLIANT,
        },
        {
            "name": "breaks",
            "kind": "written",
            "facts": [rule_cards._fact("set pressure", "13"), twelve],
            "text": "",
            "expect": dc.NON_COMPLIANT,
        },
        {
            "name": "unclear",
            "kind": "written",
            "facts": [ten],
            "text": "",
            "expect": dc.NEEDS_ENGINEER_REVIEW,
        },
    ]
    card = rule_cards.run_card(item, TYPE, RULES)
    assert {r["kind"] for r in card["runs"]} == {"written"}
    assert card["status"] == "tested", card


def test_a_card_missing_one_of_the_three_cases_is_draft():
    item = _item(SET_PRESSURE)
    item["rule"] = {
        "kind": "compare",
        "left": "set_pressure",
        "op": "<=",
        "right": "design_pressure",
    }
    item["tests"] = [
        {
            "name": "meets",
            "kind": "written",
            "facts": [
                rule_cards._fact("set pressure", "10"),
                rule_cards._fact("design pressure", "12"),
            ],
            "text": "",
            "expect": dc.COMPLIANT,
        }
    ]
    card = rule_cards.run_card(item, TYPE, RULES)
    assert (
        card["status"] == "draft"
        and card["why"] == "needs a meets, a breaks and an unclear case"
    )


def test_a_conditional_item_gets_no_generated_case():
    item = _item(SET_PRESSURE)
    item["condition"] = {"role": "fluid_phase", "any": ["gas"]}
    assert rule_cards.generated_cases(item, RULES) == []


@pytest.mark.parametrize(
    "equipment_type", ["Centrifugal Pump", "Pressure Vessel", "Heat Exchanger"]
)
def test_every_stated_rule_of_the_other_checklists_is_tested_today(equipment_type):
    """Pump 17 of 17, vessel and exchanger all but the items with a condition: the real code agrees with the
    generated cases (a regression guard for the checklists)."""
    checklist = RULES["checklists"][equipment_type]
    cards = [rule_cards.run_card(i, equipment_type, RULES) for i in checklist["items"]]
    failed = [c["id"] for c in cards if c["why"] == "a case failed"]
    assert failed == []
    assert sum(c["status"] == "tested" for c in cards) >= len(cards) - 2


def test_every_card_of_every_checklist_is_tested_by_the_real_code_today():
    """The release gate of order 296.4: `python scripts/rule_cards.py --check` exits 0. A new checklist item without
    cases, or a code change that breaks a rule, turns a card to draft and fails here."""
    report = rule_cards.report()
    assert {k: v["draft"] for k, v in report.items()} == {
        "Pressure Safety Valve": 0,
        "Centrifugal Pump": 0,
        "Pressure Vessel": 0,
        "Heat Exchanger": 0,
    }
    assert rule_cards.main(["--check"]) == 0


def test_the_area_calculation_cards_rest_on_an_independent_calculation():
    """The API 520-I gas area written out here from the published SI equation (not from the code under test) agrees
    with the area the card's case was built on, and the real code's own figure agrees with it within 0.5%."""
    import math

    w, p1, t, m, z, k = (
        9400.0,
        1000.0 + 100.0 + 101.325,
        120 + 273.15,
        30.13,
        0.892,
        1.3,
    )
    c = 520 * math.sqrt(k * (2 / (k + 1)) ** ((k + 1) / (k - 1)))
    independent = 13160 * w / (c * 0.975 * p1) * math.sqrt(t * z / m)
    assert abs(independent - 1038.4) < 0.1
    item = next(i for i in RULES["checklists"][TYPE]["items"] if i["id"] == "PSV-C01")
    case = next(
        c for c in rule_cards.written_cases(TYPE, "PSV-C01") if c["name"] == "meets"
    )
    one = {
        **RULES,
        "checklists": {TYPE: {"items": [item], "sign_off": {"status": "draft"}}},
    }
    got = next(
        r
        for r in dc.evaluate(
            case["facts"], equipment_type=TYPE, page_texts={1: "x"}, rules=one
        )
        if r["rule_id"] == "PSV-C01"
    )
    assert abs(got["calculated_mm2"] - independent) / independent < 0.005
