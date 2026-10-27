"""Order 235.2: the centrifugal-pump review checklist (a DRAFT).

A pump datasheet had no checklist, so a pump review decided nothing about its
fields. The pump checklist asks, per field an API 610 pump datasheet carries,
whether the sheet STATES it. It is a draft needing the client engineer's
approval, its clause numbers are not verified (and say so), and it does NOT
replace the standard's library requirements: API 610 stays checked clause by
clause beside it (`governs: false`). Invented values only.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import form_reader_fields
from tests.test_746_relief_valve_checklist import fact

PUMP = "Centrifugal Pump"
RULES = dc.load_rules()

#: label as a pump sheet prints it -> (role, value, unit)
SHEET = [
    ("Capacity / Flow", "rated_flow", "24.8", "m3/h"),
    ("Differential head", "rated_head", "85", "m"),
    ("NPSH required", "npsh_required", "3.2", "m"),
    ("NPSH available", "npsh_available", "6.5", "m"),
    ("Rated speed", "rated_speed", "2950", "rpm"),
    ("Absorbed power", "absorbed_power", "9.4", "kW"),
    ("Driver rating", "driver_rating", "15", "kW"),
    ("Minimum continuous stable flow", "min_flow", "9", "m3/h"),
    ("Pumping temperature", "operating_temperature", "76.7", "C"),
    ("Design pressure", "design_pressure", "25", "barg"),
    ("Design temperature", "design_temperature", "120", "C"),
    ("Casing material", "casing_material", "Carbon steel", None),
    ("Impeller material", "impeller_material", "12% Cr steel", None),
    ("Shaft material", "shaft_material", "Alloy steel", None),
    ("Seal type", "seal_type", "Single mechanical", None),
    ("Seal flush plan", "seal_plan", "Plan 11", None),
    ("Bearing type", "bearing_type", "Ball", None),
]


def _facts(skip=()):
    return [
        fact(label.lower(), value, unit, label=label)
        for label, role, value, unit in SHEET
        if role not in skip
    ]


def _results(facts, equipment_type=PUMP):
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=equipment_type, page_texts={1: "x"})
        if r.get("checklist")
    }


def test_the_pump_checklist_is_a_draft_with_unverified_clauses_and_does_not_govern():
    checklist = dc.checklist_for(PUMP, RULES)
    assert checklist["draft"] is True and checklist["governs"] is False
    entry = RULES["checklists"][PUMP]
    assert entry["sign_off"]["status"] == "draft" and entry["clauses_verified"] is False
    assert len(checklist["items"]) == 17
    for item in checklist["items"]:
        assert item["source"]["standard"] == "API 610"
        assert (
            "to be verified" in item["source"]["clause"]
        )  # no clause number is claimed
        assert (
            item["rule"]["kind"] == "required"
            and item["rule"]["field"] in RULES["roles"]
        )


def test_the_pump_checklist_does_not_replace_the_library_requirements_but_the_valve_one_does():
    assert dc.checklist_sources(PUMP, RULES)["standards"] == []
    assert dc.checklist_sources("Pressure Safety Valve", RULES)["standards"] != []
    # an alias of the type reaches the same checklist
    assert dc.checklist_for("Pump", RULES)["key"] == PUMP


@pytest.mark.parametrize("label, role, value, unit", SHEET)
def test_every_field_a_pump_sheet_prints_is_read_as_its_role(label, role, value, unit):
    assert dc.role_of(label.lower(), RULES) == role


def test_a_full_sheet_states_every_field():
    r = _results(_facts())
    assert len(r) == 17
    assert {x["status"] for x in r.values()} == {"COMPLIANT"}


def test_a_field_the_sheet_does_not_state_is_missing_and_a_blank_names_its_page():
    r = _results(_facts(skip=("npsh_available", "seal_plan")))
    assert r["PMP-04"]["status"] == "MISSING_INFORMATION"
    assert r["PMP-16"]["status"] == "MISSING_INFORMATION"
    assert r["PMP-01"]["status"] == "COMPLIANT"
    blank = [
        *_facts(skip=("rated_head",)),
        fact("differential head", "", blank="By Vendor", page=3),
    ]
    got = _results(blank)["PMP-02"]
    assert got["status"] == "MISSING_INFORMATION" and "page 3" in got["detail"]


def test_a_pump_sheet_is_not_judged_by_the_valve_checklist_and_the_valve_roles_are_unchanged():
    assert not [
        k for k in _results(_facts(), "Pressure Safety Valve") if k.startswith("PMP-")
    ]
    assert not [k for k in _results(_facts()) if k.startswith("PSV-")]
    for label, role in (
        ("set pressure", "set_pressure"),
        ("body material", "body_material"),
        ("rated capacity", "rated_flow"),
        ("design pressure", "design_pressure"),
    ):
        assert dc.role_of(label, RULES) == role


def test_the_reader_is_asked_for_the_new_pump_fields():
    keys = {f.key for f in form_reader_fields.field_list_for(PUMP)}
    for _label, role, _v, _u in SHEET:
        assert role in keys


def test_each_new_spelling_belongs_to_one_role():
    seen: dict[str, str] = {}
    for role, body in RULES["roles"].items():
        for spelling in body.get("printed_as", []):
            assert seen.setdefault(spelling.lower(), role) == role, spelling


@pytest.mark.parametrize(
    "label",
    ["plan", "head", "power", "seal", "npsh", "driver", "material", "pump"],
)
def test_a_loose_label_is_not_read_as_one_of_the_pump_fields(label):
    """A bare word is another field's (or nothing's): it must not answer a pump item."""
    assert dc.role_of(label, RULES) is None


def test_the_clause_finder_lists_references_only_never_text():
    """scripts/pump_checklist_clauses.py: clause references of the rows whose subject names a field."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "pump_checklist_clauses.py"
    spec = importlib.util.spec_from_file_location("pump_checklist_clauses", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {
            "subject": "Rated differential head",
            "clause": "6.1.1",
            "source_text": "never printed",
        },
        {"subject": "NPSH required", "clause": "6.1.5"},
        {"subject": "Differential head tolerance", "clause": "6.1.2"},
        {"subject": "Seal chamber", "clause": "6.8.1"},
    ]
    assert module.clauses_for("rated_head", RULES, rows) == ["6.1.1", "6.1.2"]
    assert module.clauses_for("npsh_required", RULES, rows) == ["6.1.5"]
    assert module.clauses_for("seal_plan", RULES, rows) == []
    # a clause whose SENTENCE names the field is offered after the subject matches, marked ?
    more = [
        *rows,
        {
            "subject": "Hydrostatic test",
            "clause": "8.3.2",
            "source_text": "The NPSH required shall be shown.",
        },
    ]
    assert module.clauses_for("npsh_required", RULES, more) == ["6.1.5", "8.3.2?"]


@pytest.mark.parametrize(
    "clause, ok",
    [
        ("6.1", True),
        ("8.3.3.5", True),
        ("L.2.4", True),
        ("K.1", True),
        ("9", True),
        ("0.005", False),
        ("", False),
        ("see 6.1", False),
        ("12345", False),
    ],
)
def test_only_something_that_looks_like_a_clause_reference_is_offered(clause, ok):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "pump_checklist_clauses.py"
    spec = importlib.util.spec_from_file_location("pump_checklist_clauses_2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [{"subject": "Rated differential head", "clause": clause}]
    assert module.clauses_for("rated_head", RULES, rows) == ([clause] if ok else [])


@pytest.mark.parametrize(
    "label",
    [
        "casing",
        "impeller",
        "shaft",
        "bearing",
        "bearings",
        "speed",
        "operating speed",
        "rated power",
        "power",
    ],
)
def test_a_bare_label_that_may_hold_a_type_or_another_figure_is_not_read_as_stated(
    label,
):
    """cloud-2's review of #1352: 'Casing' usually holds a construction, 'Speed' may be the driver's,
    'Rated power' is often the driver's. 'Stated' must not be a false pass."""
    assert dc.role_of(label, RULES) is None


@pytest.mark.parametrize(
    "label, role",
    [
        ("casing material", "casing_material"),
        ("impeller material", "impeller_material"),
        ("shaft material", "shaft_material"),
        ("bearing type", "bearing_type"),
        ("rated speed", "rated_speed"),
        ("pump speed", "rated_speed"),
        ("absorbed power", "absorbed_power"),
        ("brake power", "absorbed_power"),
    ],
)
def test_the_full_labels_still_read(label, role):
    assert dc.role_of(label, RULES) == role
