"""#900 (PF2): a field name that fits two roles is read as the one the sheet's
own equipment type checks.

PF1's first run (#881): a relief valve sheet prints "Required capacity: 5200
kg/h" and "Rated capacity: 4800 kg/h". "Rated capacity" fits a pump's rated
flow AND a relief valve's rated relieving capacity; the first in table order
(the pump's) won, so the valve checks "the rated relieving capacity is stated"
and "rated is at least required" found no rated capacity and sent both to the
engineer, and a valve smaller than its duty was not decided. Invented values only.
"""

from __future__ import annotations

from app import datasheet_checks as d
from app import datasheet_roles as r

RULES = d.load_rules()
PSV = "Pressure Safety Valve"


def _fact(name, value, unit=None, raw=None):
    return {
        "id": name,
        "field_name": name,
        "field_label": name,
        "field_value": f"{value} {unit or ''}".strip(),
        "raw_value": raw,
        "raw_unit": unit,
        "is_blank": 0,
        "blank_marker": None,
        "page": 1,
        "equipment_tag": None,
        "extraction_method": "geometry",
    }


def _run(equipment_type, rated, required=5200):
    facts = [
        _fact("Required capacity", required, "kg/h", required),
        _fact("Rated capacity", rated, "kg/h", rated),
        _fact("Design pressure", 10, "barg", 10),
        _fact("Design temperature", 150, "C", 150),
    ]
    out = d.evaluate(facts, equipment_type=equipment_type, page_texts={1: "x"})
    return {r["rule_id"]: r["status"] for r in out}


def test_a_valve_smaller_than_its_duty_is_decided_not_sent_to_the_engineer():
    got = _run(PSV, 4800)
    assert got["PSV-11"] == d.COMPLIANT  # the rated capacity is stated
    assert got["PSV-31"] == d.NON_COMPLIANT  # 4800 < 5200


def test_a_valve_at_or_above_its_duty_meets_and_never_fails():
    assert _run(PSV, 6000)["PSV-31"] == d.COMPLIANT
    assert _run(PSV, 5200)["PSV-31"] == d.COMPLIANT


def test_the_name_fits_two_roles_and_the_table_order_is_kept_without_a_preference():
    assert r.roles_of("Rated capacity", RULES) == ["rated_flow", "rated_capacity"]
    assert r.role_of("Rated capacity", RULES) == "rated_flow"
    assert (
        r.role_of("Rated capacity", RULES, frozenset({"rated_capacity"}))
        == "rated_capacity"
    )


def test_a_type_that_does_not_check_the_relief_role_still_reads_it_as_the_pump_role():
    for equipment_type in (
        "Centrifugal Pump",
        None,
        "A type the table has never heard of",
    ):
        wanted = r.wanted_roles(equipment_type, RULES)
        assert "rated_capacity" not in wanted
        assert r.role_of("Rated capacity", RULES, wanted) == "rated_flow"


def test_the_wanted_roles_come_from_the_types_own_checklist_and_mandatory_list():
    wanted = r.wanted_roles(PSV, RULES)
    assert {"rated_capacity", "required_capacity", "design_pressure"} <= wanted


def test_a_pump_only_label_on_a_valve_sheet_is_unchanged():
    assert r.role_of("Rated flow", RULES, r.wanted_roles(PSV, RULES)) == "rated_flow"


def test_the_rule_is_generic_it_names_no_label_and_no_type():
    rules = {
        "roles": {
            "a_role": {"kind": "x", "names": ["^thing$"]},
            "b_role": {"kind": "x", "names": ["^thing$"]},
        },
        "mandatory": {"_generic": [], "Widget": ["b_role"]},
        "checklists": {},
    }
    assert r.roles_of("Thing", rules) == ["a_role", "b_role"]
    assert r.role_of("Thing", rules) == "a_role"
    assert r.wanted_roles("Widget", rules) == frozenset({"b_role"})
    assert r.role_of("Thing", rules, r.wanted_roles("Widget", rules)) == "b_role"
