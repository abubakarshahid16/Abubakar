"""Order 238/240 (s2's 35B run on the M-03 pump sheet): a pump sheet's own labels for its flow and
temperature are read as those fields.

The 35B reader reads every page, so the mandatory-field check ran on facts it had never seen:
"CAPACITY / FLOW 24.8 m3/h" and "PUMPING TEMPERATURE 76.7 C" were stored under their printed
names, matched no role, and the review asked the contractor for "Rated flow" and "Operating
temperature", values the sheet gives. General: two spellings API 610 itself uses, whole labels only.
A bare "capacity", "flow" or "normal flow" is not widened (a valve's capacity is another field).
Invented values only.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc

PUMP = "Centrifugal Pump"
RULES = dc.load_rules()


@pytest.mark.parametrize(
    "label, role",
    [
        ("CAPACITY / FLOW", "rated_flow"),
        ("Capacity/Flow", "rated_flow"),
        ("Flow / Capacity", "rated_flow"),
        ("PUMPING TEMPERATURE", "operating_temperature"),
        ("Pumping temp.", "operating_temperature"),
        ("Max pumping temperature", "operating_temperature"),
        ("Normal pumping temperature", "operating_temperature"),
        # what was already read stays read
        ("Rated flow", "rated_flow"),
        ("Rated capacity", "rated_flow"),
        ("Operating temperature", "operating_temperature"),
    ],
)
def test_a_pump_sheets_own_labels_are_the_flow_and_the_temperature(label, role):
    assert dc.role_of(label, RULES) == role


@pytest.mark.parametrize(
    "label",
    [
        "Capacity",
        "Flow",
        "Normal flow",
        "Flowing temperature",
        "Pumping",
        "Temperature",
    ],
)
def test_a_looser_label_is_not_widened_into_those_fields(label):
    assert dc.role_of(label, RULES) is None


def test_a_valves_rated_relieving_capacity_is_still_the_valves_not_the_pumps():
    assert dc.role_of("Rated relieving capacity", RULES) == "rated_capacity"


def _fact(name, value, unit=None, page=2):
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": page,
        "equipment_tag": None,
    }


PAGES = {
    2: "PUMP DATA\nCAPACITY / FLOW 24.8 m3/h\nPUMPING TEMPERATURE 76.7 C\n"
    "Design pressure 10 barg\nDesign temperature 120 C\n"
}


def _asked_for(facts):
    return {
        r["rule_id"] + ":" + r["field"]
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES)
        if r["rule_id"] == "DS-M1"
    }


def test_the_contractor_is_not_asked_for_values_the_sheet_prints_under_those_labels():
    facts = [
        _fact("capacity / flow", "24.8", "m3/h"),
        _fact("pumping temperature", "76.7", "C"),
        _fact("design pressure", "10", "barg"),
        _fact("design temperature", "120", "C"),
    ]
    assert _asked_for(facts) == set()


def test_a_value_that_really_is_not_read_is_still_asked_for():
    """The fix reads two more names; it does not excuse an absence."""
    facts = [
        _fact("design pressure", "10", "barg"),
        _fact("design temperature", "120", "C"),
    ]
    messages = {
        r["detail"]
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES)
        if r["rule_id"] == "DS-M1"
    }
    assert any("Rated flow was not found" in m for m in messages)
    assert any("Operating temperature was not found" in m for m in messages)


def test_the_label_search_finds_the_page_that_prints_those_labels():
    assert dc.label_search("rated_flow", RULES, PAGES) == [2]
    assert dc.label_search("operating_temperature", RULES, PAGES) == [2]
    assert dc.label_search("rated_flow", RULES, {1: "Design pressure 10 barg"}) == []


def test_each_spelling_belongs_to_one_role():
    seen = {}
    for role, body in RULES["roles"].items():
        for spelling in body.get("printed_as", []):
            assert seen.setdefault(spelling.lower(), role) == role, spelling
