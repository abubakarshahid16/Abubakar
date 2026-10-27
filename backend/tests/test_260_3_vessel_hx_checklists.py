"""Order 260.3: the pressure-vessel and shell-and-tube heat-exchanger review checklists (DRAFTS).

Same shape as the pump checklist (#1352): per field the datasheet carries, whether the sheet STATES
it; drafts needing the client engineer's approval; no clause number claimed; they do not replace the
library standards (`governs: false`). Invented values only."""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import form_reader_fields
from tests.test_746_relief_valve_checklist import fact

VESSEL = "Pressure Vessel"
HX = "Heat Exchanger"
RULES = dc.load_rules()

#: label as a vessel sheet prints it -> (role, value, unit)
VESSEL_SHEET = [
    ("Design pressure", "design_pressure", "23.5", "barg"),
    ("Design temperature", "design_temperature", "120", "C"),
    ("Minimum design metal temperature", "mdmt", "-29", "C"),
    ("Operating pressure", "operating_pressure", "20", "barg"),
    ("Operating temperature", "operating_temperature", "90", "C"),
    ("Hydrotest pressure", "test_pressure", "30.6", "barg"),
    ("Corrosion allowance", "corrosion_allowance", "3", "mm"),
    ("Shell material", "shell_material", "SA-516 Gr 70", None),
    ("Head material", "head_material", "SA-516 Gr 70", None),
    ("Inside diameter", "inside_diameter", "1800", "mm"),
    ("Tangent to tangent length", "tangent_length", "4200", "mm"),
    ("Vessel volume", "vessel_volume", "12.4", "m3"),
    ("Joint efficiency", "joint_efficiency", "0.85", None),
    ("Radiography", "radiography", "Spot", None),
    ("PWHT", "pwht", "Not required", None),
    ("Design code", "design_code", "ASME VIII-1", None),
    ("Empty weight", "empty_weight", "5200", "kg"),
    ("Operating weight", "operating_weight", "17000", "kg"),
]

HX_SHEET = [
    ("Heat duty", "heat_duty", "1450", "kW"),
    ("Heat transfer area", "heat_transfer_area", "120", "m2"),
    ("Shell side design pressure", "design_pressure", "18", "barg"),
    ("Design temperature", "design_temperature", "200", "C"),
    ("Operating pressure", "operating_pressure", "12", "barg"),
    ("Operating temperature", "operating_temperature", "150", "C"),
    ("Hydrotest pressure", "test_pressure", "27", "barg"),
    ("Corrosion allowance", "corrosion_allowance", "3", "mm"),
    ("Shell material", "shell_material", "Carbon steel", None),
    ("Tube material", "tube_material", "SA-179", None),
    ("Tube outside diameter", "tube_outside_diameter", "19.05", "mm"),
    ("Tube wall thickness", "tube_wall_thickness", "2.11", "mm"),
    ("Tube length", "tube_length", "6000", "mm"),
    ("Number of tubes", "tube_count", "412", None),
    ("Number of tube passes", "tube_passes", "2", None),
    ("Fouling resistance", "fouling_resistance", "0.00035", None),
    ("TEMA type", "tema_type", "BEM", None),
    ("Shell side flow", "exchanger_flow", "45", "m3/h"),
    ("Allowable pressure drop", "allowable_pressure_drop", "0.5", "bar"),
]


def _facts(sheet, skip=()):
    return [
        fact(label.lower(), value, unit, label=label)
        for label, role, value, unit in sheet
        if role not in skip
    ]


def _results(facts, equipment_type):
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=equipment_type, page_texts={1: "x"})
        if r.get("checklist")
    }


@pytest.mark.parametrize(
    ("key", "prefix", "sheet", "standard"),
    [
        (VESSEL, "VSL", VESSEL_SHEET, "ASME BPVC VIII-1"),
        (HX, "HEX", HX_SHEET, "API 660 / TEMA"),
    ],
)
def test_the_checklist_is_a_draft_with_no_claimed_clause_and_does_not_govern(
    key, prefix, sheet, standard
):
    checklist = dc.checklist_for(key, RULES)
    assert checklist["draft"] is True and checklist["governs"] is False
    entry = RULES["checklists"][key]
    assert entry["sign_off"]["status"] == "draft" and entry["clauses_verified"] is False
    assert len(checklist["items"]) == len(sheet)
    for item in checklist["items"]:
        assert item["id"].startswith(prefix + "-")
        assert item["source"] == {"standard": standard, "clause": "datasheet fields"}
        assert (
            item["rule"]["kind"] == "required"
            and item["rule"]["field"] in RULES["roles"]
        )
    assert dc.checklist_sources(key, RULES)["standards"] == []


@pytest.mark.parametrize("label, role, value, unit", VESSEL_SHEET + HX_SHEET)
def test_every_field_a_sheet_prints_is_read_as_its_role(label, role, value, unit):
    assert dc.role_of(label.lower(), RULES) == role


@pytest.mark.parametrize(("key", "sheet"), [(VESSEL, VESSEL_SHEET), (HX, HX_SHEET)])
def test_a_full_sheet_states_every_field(key, sheet):
    r = _results(_facts(sheet), key)
    assert len(r) == len(sheet)
    assert {x["status"] for x in r.values()} == {"COMPLIANT"}


def test_a_field_the_sheet_does_not_state_is_missing_and_a_blank_names_its_page():
    r = _results(_facts(VESSEL_SHEET, skip=("mdmt", "pwht")), VESSEL)
    assert r["VSL-03"]["status"] == "MISSING_INFORMATION"
    assert r["VSL-15"]["status"] == "MISSING_INFORMATION"
    assert r["VSL-01"]["status"] == "COMPLIANT"
    blank = [
        *_facts(HX_SHEET, skip=("fouling_resistance",)),
        fact(
            "fouling resistance",
            "",
            blank="By Vendor",
            page=3,
            label="Fouling resistance",
        ),
    ]
    got = _results(blank, HX)["HEX-16"]
    assert got["status"] == "MISSING_INFORMATION" and "page 3" in got["detail"]


def test_a_vessel_sheet_is_not_judged_by_the_exchanger_list_and_the_other_checklists_are_unchanged():
    assert not [
        k for k in _results(_facts(VESSEL_SHEET), VESSEL) if k.startswith("HEX-")
    ]
    assert not [k for k in _results(_facts(HX_SHEET), HX) if k.startswith("VSL-")]
    assert dc.checklist_for("Centrifugal Pump", RULES)["key"] == "Centrifugal Pump"
    assert (
        dc.checklist_for("Pressure Safety Valve", RULES)["key"]
        == "Pressure Safety Valve"
    )
    for label, role in (
        ("set pressure", "set_pressure"),
        ("body material", "body_material"),
        ("rated flow", "rated_flow"),
        ("casing material", "casing_material"),
    ):
        assert dc.role_of(label, RULES) == role


@pytest.mark.parametrize(("key", "sheet"), [(VESSEL, VESSEL_SHEET), (HX, HX_SHEET)])
def test_the_reader_is_asked_for_the_new_fields(key, sheet):
    keys = {f.key for f in form_reader_fields.field_list_for(key)}
    for _label, role, _v, _u in sheet:
        assert role in keys


@pytest.mark.parametrize(
    "label",
    [
        "material",
        "diameter",
        "weight",
        "length",
        "passes",
        "number of passes",
        "no. of passes",
        "shell passes",
        "volume",
        "mdmt exemption",
        "shell",
        "tube",
        "area",
        "type",
        "code",
        "volume of work",
        "efficiency",
        "flow",
        "drop",
        "duty",
    ],
)
def test_a_loose_label_is_not_read_as_one_of_the_new_fields(label):
    new_roles = {role for _l, role, _v, _u in VESSEL_SHEET + HX_SHEET} - {
        "design_pressure",
        "design_temperature",
        "operating_pressure",
        "operating_temperature",
        "test_pressure",
        "corrosion_allowance",
    }
    assert dc.role_of(label, RULES) not in new_roles


def test_each_new_spelling_belongs_to_one_role():
    seen: dict[str, str] = {}
    for role, body in RULES["roles"].items():
        for spelling in body.get("printed_as", []):
            assert seen.setdefault(spelling.lower(), role) == role, spelling


@pytest.mark.parametrize("label", ["Number of passes", "No. of passes", "Passes"])
def test_a_bare_passes_label_does_not_state_the_tube_passes(label):
    # cloud on #1390: on a sheet where that cell is the shell-side count it would be a false "stated".
    assert dc.role_of(label.lower(), RULES) != "tube_passes"
    facts = [
        *_facts(HX_SHEET, skip=("tube_passes",)),
        fact(label.lower(), "1", None, label=label),
    ]
    assert _results(facts, HX)["HEX-15"]["status"] == "MISSING_INFORMATION"


@pytest.mark.parametrize(
    "label", ["Number of tube side passes", "No. of tube passes", "Tube side passes"]
)
def test_a_label_naming_the_tube_side_states_the_tube_passes(label):
    assert dc.role_of(label.lower(), RULES) == "tube_passes"


def test_a_two_sided_item_says_one_side_is_enough_to_pass():
    items = {i["id"]: i["text"] for i in dc.checklist_for(HX, RULES)["items"]}
    for item_id in ("HEX-16", "HEX-18", "HEX-19"):
        assert "one side is enough" in items[item_id]
    one_side = [
        *_facts(HX_SHEET, skip=("exchanger_flow",)),
        fact("tube side flow", "30", "m3/h", label="Tube side flow"),
    ]
    assert _results(one_side, HX)["HEX-18"]["status"] == "COMPLIANT"


def test_a_plate_heat_exchanger_takes_the_shell_and_tube_list():
    # Scope, stated in the PR: the list is a draft for shell-and-tube; a plate unit is judged by it too
    # and so reads "not found" for tube passes, tube count and TEMA type until a plate list exists.
    assert dc.checklist_for("Plate Heat Exchanger", RULES)["key"] == HX
