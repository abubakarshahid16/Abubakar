"""Order 296: a rule card is tested with the REAL checking code. Invented rules only."""

from __future__ import annotations

import copy
import pytest

from app import datasheet_checks as dc
from app import rule_cards

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


#: Order 301.1: where the nine "is stated" cards that cited a definition now point (the clause that REQUIRES the value).
REQUIRING_CLAUSES = {
    "PSV-01": ("SAES-J-600", "8"),
    "PSV-02": ("SAES-J-600", "8.3"),
    "PSV-03": ("SAES-J-600", "8.16"),
    "PSV-04": ("SAES-J-600", "8"),
    "PSV-07": ("API 520-I", "5.3.4.1"),
    "PSV-08": ("API 520-I", "4.2.1.3.6"),
    "PSV-11": ("SAES-J-600", "8.13.1"),
    "PSV-14": ("SAES-J-600", "4.1.2"),
    "PSV-15": ("API 520-I", "5.3.4.1"),
}


def _items(equipment_type: str = TYPE) -> dict:
    return {i["id"]: i for i in RULES["checklists"][equipment_type]["items"]}


def test_every_relief_valve_card_is_tested_except_the_two_that_need_a_standard_we_do_not_hold():
    """Order 301.1: 47 cards, 45 tested; PSV-05 and PSV-25 stay draft and say what they wait for. `--check` passes
    because both drafts are declared; an unexplained draft still fails it (next test)."""
    report = rule_cards.report()
    assert report[TYPE]["cards"] == 47
    assert report[TYPE]["tested"] == 45 and report[TYPE]["draft"] == 2
    assert report[TYPE]["draft_because"] == {"needs a standard we do not hold": 2}
    assert [k for k, v in report.items() if k != TYPE and v["draft"]] == []
    drafts = {
        i["id"]
        for i in RULES["checklists"][TYPE]["items"]
        if rule_cards.run_card(i, TYPE, RULES)["status"] == "draft"
    }
    assert drafts == {"PSV-05", "PSV-25"}
    assert rule_cards.main(["--check"]) == 0


def test_a_draft_nobody_explained_still_fails_the_gate(monkeypatch):
    real = rule_cards.report()
    real[TYPE]["draft"] += 1
    real[TYPE]["draft_because"]["a case failed"] = 1
    monkeypatch.setattr(rule_cards, "report", lambda: real)
    assert rule_cards.main(["--check"]) == 1


def test_a_card_that_names_what_it_needs_is_draft_whatever_its_cases_say():
    item = _item(SET_PRESSURE)
    item["needs"] = "a standard we do not hold"
    card = rule_cards.run_card(item, TYPE, RULES)
    assert (card["status"], card["why"]) == ("draft", "needs a standard we do not hold")
    assert all(r["passed"] for r in card["runs"])  # not a failing card: a waiting one
    del item["needs"]
    assert rule_cards.run_card(item, TYPE, RULES)["status"] == "tested"


def test_the_nine_cards_cite_the_clause_that_requires_the_value():
    items = _items()
    for card_id, (standard, clause) in REQUIRING_CLAUSES.items():
        assert (
            items[card_id]["source"]["standard"],
            items[card_id]["source"]["clause"],
        ) == (standard, clause)
        assert not rule_cards.cites_a_definition(items[card_id])


def test_the_weak_sources_are_marked_on_the_card():
    items = _items()
    assert sorted(i for i, item in items.items() if item.get("weak_source")) == [
        "PSV-03",
        "PSV-15",
    ]
    assert rule_cards.report()[TYPE]["weak_source"] == ["PSV-03", "PSV-15"]
    assert rule_cards.run_card(items["PSV-03"], TYPE, RULES)["weak_source"] is True
    assert rule_cards.run_card(items["PSV-01"], TYPE, RULES)["weak_source"] is False


def test_no_card_cites_an_asme_viii_row_stored_under_clause_7_16():
    """Order 301.1: those rows' clause numbers are not ASME's own yet (clause-attribution gap)."""
    for checklist in RULES["checklists"].values():
        for item in checklist["items"] if isinstance(checklist, dict) else []:
            source = item["source"]
            assert not (
                "ASME" in source["standard"].upper()
                and str(source["clause"]).startswith("7.16")
            )


def test_the_margin_card_is_one_card_with_the_clauses_own_numbers():
    """Order 301.1: PSV-26 (a margin the clause does not state) was merged into PSV-S03."""
    items = _items()
    assert "PSV-26" not in items
    rule = items["PSV-S03"]["rule"]
    assert items["PSV-S03"]["source"] == {"standard": "SAES-J-600", "clause": "8"}
    assert (rule["kind"], rule["left"], rule["right"]) == (
        "above_by",
        "set_pressure",
        "operating_pressure",
    )
    assert (rule["percent"], rule["at_least"], rule["unit"]) == (10, 100, "kPa")


def test_a_card_citing_a_requirement_clause_is_not_held_back_by_the_definition_rule():
    item = _item(SET_PRESSURE)
    item["source"] = {"standard": "API 520-I", "clause": "5.4.2.1.1"}
    assert not rule_cards.cites_a_definition(item)
    item["source"] = {"standard": "API 520-I", "clause": "3.49"}
    assert rule_cards.cites_a_definition(item)
    item["source"] = {"standard": "OTHER STD", "clause": "3.49"}
    assert not rule_cards.cites_a_definition(item)  # only the standards the data names


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
