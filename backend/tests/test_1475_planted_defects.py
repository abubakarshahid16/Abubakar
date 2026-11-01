"""#1475 planted-defect sets for datasheets: invented sheets, invented values, no model, no database.

Why: 77 saved review runs produced 0 NON_COMPLIANT rows. Before anyone changes the code, the question is
whether the CODE can say Fail on a defect at all, through every gate. The answer is measured here, on the
PF1 pattern (#881): each invented sheet plants defects (a value outside a limit, a required value missing, a
value the sheet defers to the contractor) next to traps (inside the limit, exactly at it) and the test
asserts the two numbers that matter:

  * every planted defect is caught (the decided status is NON_COMPLIANT / MISSING_INFORMATION / a query);
  * 0 false passes (no planted defect, and no deferred value, ever reads COMPLIANT).

Two layers: the datasheet checklist and self-checks (`datasheet_checks.evaluate`, then `rule_trust.label_check`
with the owner's trust switches ON, as the live setup runs) and the standards comparison
(`comparison.compare`). The deferred-value rule (owner decision D2) is behind its own switch,
`deferred_value_is_query_enabled`, OFF by default: both positions are tested.

Procedure planted defects wait for #1476 (the NOT_IN_DOCUMENT_SCOPE branches).
"""

from __future__ import annotations

import pytest

from app import comparison, deferred_value, rule_trust
from app import datasheet_checks as dc
from app.config import settings

PSV = "Pressure Safety Valve"
VESSEL = "Pressure Vessel"
PUMP = "Centrifugal Pump"
EXCHANGER = "Heat Exchanger"
PAGES = {1: "Rev Description Prepared Checked\n0 Issued for review"}
PRESSURE_UNITS = ("barg", "bara")


def _fact(name, value, unit=None, *, note=None, blank=None, tag=None):
    printed = " ".join(x for x in (value, unit, note) if x)
    pressure = unit in PRESSURE_UNITS
    return {
        "id": f"f-{name}-{value}-{tag}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": printed,
        "raw_value": None if blank else value,
        "raw_unit": unit,
        "normalized_value": float(value) / 10 if pressure and not blank else None,
        "normalized_unit": "MPa" if pressure and not blank else None,
        "is_blank": 1 if blank else 0,
        "blank_marker": blank,
        "page": 1,
        "equipment_tag": tag,
        "value_note": note,
    }


def _sheet(base, **changes):
    """The base rows with some replaced (value, unit) or, for None, removed. Keys use underscores."""
    rows = {}
    for row in base:
        rows[row[0].replace(" ", "_")] = row
    for key, new in changes.items():
        if new is None:
            rows.pop(key, None)
        else:
            rows[key] = (key.replace("_", " "), *new)
    return list(rows.values())


def _run(rows, equipment_type, **notes):
    facts = [
        _fact(*r) if r[0] not in notes else _fact(*r, note=notes[r[0]]) for r in rows
    ]
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=equipment_type, page_texts=PAGES)
    }


PSV_BASE = [
    ("set pressure", "10", "barg"),
    ("maximum allowable working pressure", "12", "barg"),
    ("design pressure", "11", "barg"),
    ("operating pressure", "7", "barg"),
    ("valve type", "conventional"),
    ("fluid phase", "liquid"),
    ("inlet rating", "300"),
    ("relief case", "blocked outlet"),
    ("overpressure", "10", "%"),
    ("built up back pressure", "8", "%"),
    ("cold differential test pressure", "9.5", "barg"),
    ("required capacity", "100", "m3/h"),
    ("rated capacity", "120", "m3/h"),
]
VESSEL_BASE = [
    ("design pressure", "23.5", "barg"),
    ("operating pressure", "20", "barg"),
    ("hydrotest pressure", "30.6", "barg"),
    ("design temperature", "120", "C"),
    ("operating temperature", "90", "C"),
    ("corrosion allowance", "3", "mm"),
]
PUMP_BASE = [
    ("design pressure", "30", "barg"),
    ("operating pressure", "22", "barg"),
    ("rated flow", "120", "m3/h"),
    ("minimum continuous flow", "10", "m3/h"),
    ("maximum flow", "200", "m3/h"),
]

#: (id, equipment type, base rows, changes, rule id that must read NON_COMPLIANT)
PLANTED = [
    ("psv set above MAWP", PSV, PSV_BASE, {"set_pressure": ("13", "barg")}, "PSV-24"),
    (
        "psv MAWP below design",
        PSV,
        PSV_BASE,
        {"maximum_allowable_working_pressure": ("10.5", "barg")},
        "PSV-25",
    ),
    (
        "psv CDTP above set",
        PSV,
        PSV_BASE,
        {"cold_differential_test_pressure": ("11", "barg")},
        "PSV-30",
    ),
    (
        "psv rated below required",
        PSV,
        PSV_BASE,
        {"rated_capacity": ("80", "m3/h")},
        "PSV-31",
    ),
    ("psv valve type not allowed", PSV, PSV_BASE, {"valve_type": ("gate",)}, "PSV-16"),
    (
        "psv inlet rating not allowed",
        PSV,
        PSV_BASE,
        {"inlet_rating": ("175",)},
        "PSV-S02",
    ),
    (
        "psv overpressure 25 percent, blocked case",
        PSV,
        PSV_BASE,
        {"overpressure": ("25", "%")},
        "PSV-28",
    ),
    (
        "psv back pressure 15 percent, conventional",
        PSV,
        PSV_BASE,
        {"built_up_back_pressure": ("15", "%")},
        "PSV-29",
    ),
    (
        "psv set not above operating by the margin",
        PSV,
        PSV_BASE,
        {"set_pressure": ("7.5", "barg")},
        "PSV-S03",
    ),
    (
        "vessel design below operating",
        VESSEL,
        VESSEL_BASE,
        {"design_pressure": ("18", "barg")},
        "DS-C1",
    ),
    (
        "vessel design temp below operating",
        VESSEL,
        VESSEL_BASE,
        {"design_temperature": ("80", "C")},
        "DS-C2",
    ),
    (
        "vessel test pressure below design",
        VESSEL,
        VESSEL_BASE,
        {"hydrotest_pressure": ("23.5", "barg")},
        "DS-C3",
    ),
    (
        "vessel pressure in a temperature unit",
        VESSEL,
        VESSEL_BASE,
        {"design_pressure": ("23.5", "C")},
        "DS-U2",
    ),
    (
        "pump rated flow below minimum",
        PUMP,
        PUMP_BASE,
        {"rated_flow": ("5", "m3/h")},
        "DS-C4",
    ),
    (
        "pump rated flow above maximum",
        PUMP,
        PUMP_BASE,
        {"rated_flow": ("500", "m3/h")},
        "DS-C5",
    ),
]

#: Traps: values inside the limit, or exactly at it. Each must read COMPLIANT and never NON_COMPLIANT.
TRAPS = [
    (
        "psv set exactly at MAWP",
        PSV,
        PSV_BASE,
        {
            "set_pressure": ("12", "barg"),
            "cold_differential_test_pressure": ("11", "barg"),
        },
        "PSV-24",
    ),
    (
        "psv overpressure exactly 10 percent",
        PSV,
        PSV_BASE,
        {"overpressure": ("10", "%")},
        "PSV-28",
    ),
    (
        "psv rated exactly the required capacity",
        PSV,
        PSV_BASE,
        {"rated_capacity": ("100", "m3/h")},
        "PSV-31",
    ),
    ("psv inlet rating allowed", PSV, PSV_BASE, {"inlet_rating": ("600",)}, "PSV-S02"),
    (
        "vessel design exactly operating",
        VESSEL,
        VESSEL_BASE,
        {"design_pressure": ("20", "barg"), "hydrotest_pressure": ("30.6", "barg")},
        "DS-C1",
    ),
    (
        "pump rated exactly the minimum",
        PUMP,
        PUMP_BASE,
        {"rated_flow": ("10", "m3/h")},
        "DS-C4",
    ),
    (
        "pump rated exactly the maximum",
        PUMP,
        PUMP_BASE,
        {"rated_flow": ("200", "m3/h")},
        "DS-C5",
    ),
]

#: (id, type, base rows, field removed, rule id of the MISSING_INFORMATION it must raise)
MISSING = [
    (
        "vessel without design temperature",
        VESSEL,
        VESSEL_BASE,
        "design_temperature",
        "DS-M1",
    ),
    (
        "vessel without operating pressure",
        VESSEL,
        VESSEL_BASE,
        "operating_pressure",
        "DS-M1",
    ),
    ("pump without rated flow", PUMP, PUMP_BASE, "rated_flow", "DS-M1"),
]


def _scenario(base, changes):
    return _sheet(base, **changes)


@pytest.mark.parametrize(
    "name, equipment_type, base, changes, rule_id", PLANTED, ids=[p[0] for p in PLANTED]
)
def test_a_planted_out_of_limit_value_is_a_fail_never_a_pass(
    name, equipment_type, base, changes, rule_id
):
    result = _run(_scenario(base, changes), equipment_type)[rule_id]
    assert result["status"] == "NON_COMPLIANT", (
        name,
        result["status"],
        result["detail"],
    )


@pytest.mark.parametrize(
    "name, equipment_type, base, changes, rule_id", TRAPS, ids=[t[0] for t in TRAPS]
)
def test_a_value_at_or_inside_the_limit_is_not_flagged(
    name, equipment_type, base, changes, rule_id
):
    result = _run(_scenario(base, changes), equipment_type)[rule_id]
    assert result["status"] == "COMPLIANT", (name, result["status"], result["detail"])


def test_the_clean_base_sheets_raise_no_fail():
    for equipment_type, base in (
        (PSV, PSV_BASE),
        (VESSEL, VESSEL_BASE),
        (PUMP, PUMP_BASE),
    ):
        results = _run(base, equipment_type)
        assert not [r for r in results.values() if r["status"] == "NON_COMPLIANT"], (
            equipment_type
        )


@pytest.mark.parametrize(
    "name, equipment_type, base, removed, rule_id", MISSING, ids=[m[0] for m in MISSING]
)
def test_a_missing_required_value_is_missing_information_never_a_pass(
    name, equipment_type, base, removed, rule_id
):
    results = dc.evaluate(
        [_fact(*r) for r in _sheet(base, **{removed: None})],
        equipment_type=equipment_type,
        page_texts=PAGES,
    )
    role = removed
    hit = [r for r in results if r["rule_id"] == rule_id and r["role"] == role]
    assert hit and all(r["status"] == "MISSING_INFORMATION" for r in hit), (
        name,
        results,
    )


def test_the_planted_totals_are_every_defect_caught_and_zero_false_passes():
    """The number the issue asks for, counted in one place: defects caught / planted, false passes."""
    caught = false_pass = 0
    for _name, equipment_type, base, changes, rule_id in PLANTED:
        status = _run(_scenario(base, changes), equipment_type)[rule_id]["status"]
        caught += status == "NON_COMPLIANT"
        false_pass += status == "COMPLIANT"
    assert (caught, false_pass) == (len(PLANTED), 0)


# --------------------------------------------------------- through the trust gate, as the live setup runs


@pytest.fixture
def live_trust(monkeypatch):
    """The owner's trust switches ON: an unproven rule never decides, a tested card does."""
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)


def _after_trust(rule_id, equipment_type, base, changes):
    return rule_trust.label_check(
        _run(_scenario(base, changes), equipment_type)[rule_id]
    )


def test_a_tested_card_fail_survives_the_trust_gate(live_trust):
    out = _after_trust("PSV-24", PSV, PSV_BASE, {"set_pressure": ("13", "barg")})
    assert out["status"] == "NON_COMPLIANT"
    assert out["trust_label"] == rule_trust.TESTED_CARD


@pytest.mark.parametrize(
    "rule_id, equipment_type, base, changes",
    [
        ("PSV-16", PSV, PSV_BASE, {"valve_type": ("gate",)}),
        ("PSV-S02", PSV, PSV_BASE, {"inlet_rating": ("175",)}),
        (
            "PSV-25",
            PSV,
            PSV_BASE,
            {"maximum_allowable_working_pressure": ("10.5", "barg")},
        ),
        ("DS-C1", VESSEL, VESSEL_BASE, {"design_pressure": ("18", "barg")}),
        ("DS-C4", PUMP, PUMP_BASE, {"rated_flow": ("5", "m3/h")}),
        ("DS-U2", VESSEL, VESSEL_BASE, {"design_pressure": ("23.5", "C")}),
    ],
)
def test_an_unproven_rules_fail_waits_for_the_engineer_and_is_never_a_pass(
    live_trust, rule_id, equipment_type, base, changes
):
    """The one gate that can hold a Fail: the rule is not engineer-confirmed or tested, so the verdict
    becomes a query and the rule's own word is kept. It is a hold, not a loss: `rule_said` says Fail."""
    out = _after_trust(rule_id, equipment_type, base, changes)
    assert (
        out["status"] == "NEEDS_ENGINEER_REVIEW" and out["rule_said"] == "NON_COMPLIANT"
    ), out
    assert out["status"] != "COMPLIANT"


# --------------------------------------------------------- D2: a deferred value is a query

DEFERRED_PSV = [
    # (field with the note, rule that reads it)
    ("set pressure", "PSV-24"),
    ("overpressure", "PSV-28"),
    ("inlet rating", "PSV-S02"),
]


@pytest.fixture
def d2_on(monkeypatch):
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", True)


@pytest.mark.parametrize("field, rule_id", DEFERRED_PSV)
def test_d2_switch_off_keeps_the_pass_on_a_deferred_value(field, rule_id, monkeypatch):
    """Pins the OFF position: nothing changes until the owner switches it on."""
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", False)
    result = _run(PSV_BASE, PSV, **{field: "By Contractor"})[rule_id]
    assert result["status"] == "COMPLIANT"


@pytest.mark.parametrize("field, rule_id", DEFERRED_PSV)
def test_d2_a_deferred_value_is_a_query_never_a_pass(field, rule_id, d2_on):
    result = _run(PSV_BASE, PSV, **{field: "By Contractor"})[rule_id]
    assert result["status"] == "NEEDS_ENGINEER_REVIEW", result
    assert "By Contractor" in result["detail"]


def test_d2_a_deferred_value_that_would_also_breach_is_a_query_not_a_fail(d2_on):
    rows = _sheet(PSV_BASE, set_pressure=("13", "barg"))
    assert (
        _run(rows, PSV, **{"set pressure": "TBA"})["PSV-24"]["status"]
        == "NEEDS_ENGINEER_REVIEW"
    )


def test_d2_a_deferred_right_hand_value_is_a_query(d2_on):
    result = _run(
        PSV_BASE, PSV, **{"maximum allowable working pressure": "By Contractor"}
    )["PSV-24"]
    assert (
        result["status"] == "NEEDS_ENGINEER_REVIEW" and "deferred" in result["detail"]
    )


def test_d2_a_deferred_self_check_pair_is_a_query(d2_on):
    result = _run(VESSEL_BASE, VESSEL, **{"operating pressure": "By Contractor"})[
        "DS-C1"
    ]
    assert result["status"] == "NEEDS_ENGINEER_REVIEW"


def test_d2_a_value_with_no_note_is_still_decided(d2_on):
    assert _run(PSV_BASE, PSV)["PSV-24"]["status"] == "COMPLIANT"
    assert (
        _run(_sheet(PSV_BASE, set_pressure=("13", "barg")), PSV)["PSV-24"]["status"]
        == "NON_COMPLIANT"
    )


def test_d2_a_plain_note_that_is_not_a_deferral_does_not_hold_the_value(d2_on):
    assert (
        _run(PSV_BASE, PSV, **{"set pressure": "as per code"})["PSV-24"]["status"]
        == "COMPLIANT"
    )


def test_d2_a_bare_deferred_marker_is_still_missing_information(d2_on):
    rows = _sheet(VESSEL_BASE, design_temperature=("By Contractor",))
    results = dc.evaluate(
        [
            _fact(*r, blank="By Contractor")
            if r[0] == "design temperature"
            else _fact(*r)
            for r in rows
        ],
        equipment_type=VESSEL,
        page_texts=PAGES,
    )
    assert [
        r
        for r in results
        if r["rule_id"] == "DS-M2" and r["status"] == "MISSING_INFORMATION"
    ]


# --------------------------------------------------------- the standards comparison (`comparison.compare`)


def _requirement(operator, value, unit):
    return {
        "id": "r",
        "standard_document_id": None,
        "requirement_type": "numeric_limit",
        "requirement_text": "An invented limit.",
        "operator": operator,
        "raw_value": value,
        "raw_unit": unit,
        "field": "design temperature",
        "exceptions": [],
    }


def _datasheet_fact(value, unit, *, note=None, blank=None):
    return {
        "id": "f",
        "document_id": None,
        "field_name": "design temperature",
        "field_label": "Design temperature",
        "field_value": " ".join(x for x in (value, unit, note) if x),
        "raw_value": None if blank else value,
        "raw_unit": unit,
        "is_blank": 1 if blank else 0,
        "blank_marker": blank,
        "value_note": note,
    }


#: (operator, limit, limit unit, sheet value, sheet unit, expected status)
COMPARE_PLANTED = [
    ("<=", "100", "C", "120", "C", "NON_COMPLIANT"),
    (">=", "50", "C", "40", "C", "NON_COMPLIANT"),
    ("<=", "10", "bar", "12", "bar", "NON_COMPLIANT"),
    ("<=", "10", "bar", "1300", "kPa", "NON_COMPLIANT"),  # another unit, still outside
    ("<=", "212", "F", "120", "C", "NON_COMPLIANT"),  # 120 C is 248 F
    (">=", "6", "mm", "5.9", "mm", "NON_COMPLIANT"),
    ("<=", "100", "C", "100", "C", "COMPLIANT"),  # trap: exactly at the limit
    ("<=", "100", "C", "80", "C", "COMPLIANT"),  # trap: inside
    ("<=", "10", "bar", "900", "kPa", "COMPLIANT"),  # trap: inside, in another unit
    (">=", "6", "mm", "6", "mm", "COMPLIANT"),  # trap: exactly at the limit
]


@pytest.mark.parametrize("op, limit, lunit, value, vunit, expected", COMPARE_PLANTED)
def test_compare_decides_a_planted_limit_both_ways(
    op, limit, lunit, value, vunit, expected
):
    verdict = comparison.compare(
        _requirement(op, limit, lunit), _datasheet_fact(value, vunit)
    )
    assert verdict["status"] == expected, verdict["rationale"]


def test_compare_totals_every_planted_breach_is_a_fail_and_no_trap_is_flagged():
    planted = [c for c in COMPARE_PLANTED if c[5] == "NON_COMPLIANT"]
    traps = [c for c in COMPARE_PLANTED if c[5] == "COMPLIANT"]
    seen = [
        comparison.compare(_requirement(c[0], c[1], c[2]), _datasheet_fact(c[3], c[4]))[
            "status"
        ]
        for c in planted
    ]
    trap_seen = [
        comparison.compare(_requirement(c[0], c[1], c[2]), _datasheet_fact(c[3], c[4]))[
            "status"
        ]
        for c in traps
    ]
    assert seen.count("NON_COMPLIANT") == len(planted) and "COMPLIANT" not in seen
    assert (
        trap_seen.count("COMPLIANT") == len(traps) and "NON_COMPLIANT" not in trap_seen
    )


def test_compare_a_missing_or_blank_value_is_missing_information_never_a_pass():
    requirement = _requirement("<=", "100", "C")
    assert comparison.compare(requirement, None)["status"] == "MISSING_INFORMATION"
    blank = comparison.compare(
        requirement, _datasheet_fact("", "", blank="By Contractor")
    )
    assert blank["status"] == "MISSING_INFORMATION"


@pytest.mark.parametrize(
    "value, expected_off", [("80", "COMPLIANT"), ("120", "NON_COMPLIANT")]
)
def test_compare_d2_off_compares_a_value_marked_by_contractor_as_before(
    value, expected_off, monkeypatch
):
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", False)
    verdict = comparison.compare(
        _requirement("<=", "100", "C"),
        _datasheet_fact(value, "C", note="By Contractor"),
    )
    assert verdict["status"] == expected_off
    assert "By Contractor" in verdict["rationale"]


@pytest.mark.parametrize("value", ["80", "120"])
def test_compare_d2_on_a_value_marked_by_contractor_is_a_query_either_way(value, d2_on):
    verdict = comparison.compare(
        _requirement("<=", "100", "C"),
        _datasheet_fact(value, "C", note="By Contractor"),
    )
    assert verdict["status"] == "NEEDS_ENGINEER_REVIEW"
    assert deferred_value.DEFERRED_VALUE in verdict["rationale"]
    assert verdict["limit"] and verdict["observed"]


def test_compare_d2_on_leaves_an_unmarked_value_decided(d2_on):
    requirement = _requirement("<=", "100", "C")
    assert (
        comparison.compare(requirement, _datasheet_fact("120", "C"))["status"]
        == "NON_COMPLIANT"
    )
    assert (
        comparison.compare(requirement, _datasheet_fact("80", "C"))["status"]
        == "COMPLIANT"
    )


# --------------------------------------------------------- sizing calculations rest on their inputs


def _sizing_sheet(orifice, **deferred):
    from tests.test_746_relief_valve_checklist import fact as psv_fact
    from tests.test_777_api520_calcs import GAS

    rows = [
        psv_fact(
            f["field_name"],
            f["field_value"].split(" ")[0],
            f["raw_unit"],
            note=deferred[f["field_name"]],
        )
        if f["field_name"] in deferred
        else f
        for f in GAS
    ]
    return rows + [psv_fact("orifice area", *orifice)]


def _c01(rows):
    found = dc.evaluate(rows, equipment_type=PSV, page_texts={1: "x"})
    return next(r for r in found if r["rule_id"] == "PSV-C01")


def test_d2_off_a_sizing_calculation_on_a_deferred_input_is_decided_as_before(
    monkeypatch,
):
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", False)
    sheet = _sizing_sheet(("6.38", "in2"), **{"set pressure": "By Contractor"})
    assert _c01(sheet)["status"] == "COMPLIANT"


@pytest.mark.parametrize(
    "orifice, said", [(("6.38", "in2"), "COMPLIANT"), (("1", "in2"), "NON_COMPLIANT")]
)
def test_d2_a_sizing_calculation_on_a_deferred_input_is_a_query_either_way(
    d2_on, orifice, said
):
    assert _c01(_sizing_sheet(orifice))["status"] == said
    held = _c01(_sizing_sheet(orifice, **{"set pressure": "By Contractor"}))
    assert held["status"] == "NEEDS_ENGINEER_REVIEW" and said in held["detail"]


def test_d2_a_sizing_calculation_with_no_deferred_input_is_unchanged(d2_on):
    assert _c01(_sizing_sheet(("6.38", "in2")))["status"] == "COMPLIANT"


def test_d2_the_held_comparison_rationale_leads_with_its_own_code(d2_on):
    verdict = comparison.compare(
        _requirement("<=", "100", "C"), _datasheet_fact("80", "C", note="By Contractor")
    )
    assert verdict["rationale"].startswith("deferred_value: ")
    assert "LOW_TRUST_VALUE" not in verdict["rationale"]


def test_code_for_pins_the_low_trust_spelling():
    low = deferred_value.code_for("the value was read by OCR")
    assert low == comparison.LOW_TRUST_VALUE + ": "
