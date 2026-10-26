"""Order 223: the same number and unit with a note is ONE value.

The owner's X-ray of a relief-valve run showed about 33 "two different values on
the sheet" rows where the reader had stored one value twice, `340 psig` and
`340 psig (By Contractor, as per Code)`, under one tag. The check compared the
printed TEXT, so the note made a second value. It now compares what the value
IS (number, unit, gauge/absolute); a different number, a different unit or basis,
or a note that changes the meaning stays two values. Made-up values only.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import same_value
from tests.test_746_relief_valve_checklist import PSV, SHEET
from tests.test_746_relief_valve_checklist import fact as psv_fact
from tests.test_datasheet_checks import PAGES, VESSEL, P, full_vessel


def _with_note(name: str, value: str, note: str, unit: str = "barg") -> dict:
    f = P(name, value, unit)
    return {
        **f,
        "id": f"{f['id']}-noted",
        "field_value": f"{value} {unit} {note}",
        "page": 2,
    }


def _result(facts, rule_id="DS-C1"):
    results = dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES)
    return next(r for r in results if r["rule_id"] == rule_id)


def test_the_same_number_with_a_note_is_one_value_and_is_compared():
    facts = [
        *full_vessel(),
        _with_note("design pressure", "23.5", "(By Contractor, as per Code)"),
    ]
    assert _result(facts)["status"] == "COMPLIANT"


def test_a_trailing_note_after_the_unit_is_still_one_value():
    facts = [*full_vessel(), _with_note("operating pressure", "20", "Note - 2")]
    assert _result(facts)["status"] == "COMPLIANT"


def test_a_different_number_stays_two_values_for_the_engineer():
    result = _result([*full_vessel(), P("design pressure", "15")])
    assert result["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in result["detail"]


def test_the_same_number_with_a_note_does_not_hide_a_real_breach():
    # design 18 (with a note, twice) is still below operating 20
    facts = [
        *full_vessel(**{"design pressure": P("design pressure", "18")}),
        _with_note("design pressure", "18", "(per Code)"),
    ]
    assert _result(facts)["status"] == "NON_COMPLIANT"


def test_each_tag_is_judged_on_its_own_values():
    def tagged(name, value, tag):
        return {**P(name, value), "equipment_tag": tag, "id": f"{name}-{value}-{tag}"}

    facts = [
        tagged("design pressure", "23.5", "V-1"),
        {**_with_note("design pressure", "23.5", "(per Code)"), "equipment_tag": "V-1"},
        tagged("operating pressure", "20", "V-1"),
        tagged("design pressure", "18", "V-2"),
        tagged("operating pressure", "20", "V-2"),
    ]
    results = dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES)
    by_tag = {
        r["equipment_tag"]: r["status"] for r in results if r["rule_id"] == "DS-C1"
    }
    assert by_tag == {"V-1": "COMPLIANT", "V-2": "NON_COMPLIANT"}


def test_a_field_a_checklist_item_reads_may_carry_a_note_twice():
    """The `_one` site: PSV-24 reads the set pressure and the MAWP."""
    noted = psv_fact("set pressure", "10", "barg")
    noted = {
        **noted,
        "id": "f-sp-noted",
        "field_value": "10 barg (By Contractor, as per Code)",
    }
    results = {
        r["rule_id"]: r
        for r in dc.evaluate([*SHEET, noted], equipment_type=PSV, page_texts={1: "x"})
        if r.get("checklist")
    }
    assert results["PSV-24"]["status"] == "COMPLIANT"
    assert results["PSV-01"]["status"] == "COMPLIANT"


def _f(raw, unit, text=None):
    return {"raw_value": raw, "raw_unit": unit, "field_value": text or f"{raw} {unit}"}


@pytest.mark.parametrize(
    "note",
    [
        "(By Contractor, as per Code)",
        "Note - 2",
        f"Note {chr(0x2013)} 2",
        "(see data sheet note)",
    ],
)
def test_a_plain_note_does_not_make_a_second_value(note):
    assert same_value.key(_f("340", "psig", f"340 psig {note}")) == same_value.key(
        _f("340", "psig")
    )


@pytest.mark.parametrize(
    "text",
    [
        "340 psig at 20 C",
        "340 psig @ 120 C",
        "340 psig (max)",
        "340 psig (min)",
        "not 340 psig",
        "340 psig except start-up",
        "340 psig per 100 m",
        "340 psig - 2 bar",
    ],
)
def test_a_note_that_changes_the_meaning_stays_a_second_value(text):
    assert same_value.key(_f("340", "psig", text)) != same_value.key(_f("340", "psig"))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (_f("20", "barg"), _f("20", "bara")),
        (_f("340", "psig"), _f("340", "psia")),
        (_f("5", "kg/hr"), _f("5", "t/hr")),
        (_f("-340", "psig"), _f("340", "psig")),
        (_f("340", "psig"), _f("130", "psig")),
        ({"field_value": "Open"}, {"field_value": "Closed"}),
    ],
)
def test_different_numbers_units_bases_and_text_stay_apart(a, b):
    assert same_value.key(a) != same_value.key(b)
