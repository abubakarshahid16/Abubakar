"""s2's 35B run on the M-03 pump sheet: "24.8 (109) m3/h (USGPM)" has a unit.

The AI reader stored the cell as printed. The cell reader met the bracketed second number where it
expected the unit, kept "24.8" with no unit, and the mandatory-unit check said "stated as '24.8 (109)
m3/h (USGPM)' on page 2 without a unit": false, the unit is printed. The first system is the value
(as "24.8 m3/h (109 USGPM)" already was). Invented values only.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import datasheets, dual_unit_form


def _measure(text):
    value, unit, measurement = datasheets.measure_value(text)
    return value, unit, (measurement.normalized_value if measurement else None)


@pytest.mark.parametrize(
    "text, value, unit",
    [
        ("24.8 (109) m3/h (USGPM)", "24.8", "m3/h"),
        (
            "24.8 (30) m3/h (USGPM)",
            "24.8",
            "m3/h",
        ),  # the second unit cannot be converted
        ("76.7 (170) C (F)", "76.7", "C"),
        ("76.7 (170) °C (°F)", "76.7", "°C"),
        ("10 (145) bar (psi)", "10", "bar"),
        ("340 (23.4) psig (barg)", "340", "psig"),
        ("  24.8   (109)  m3/h  (USGPM) ", "24.8", "m3/h"),
    ],
)
def test_the_first_system_is_the_value_and_its_unit_is_kept(text, value, unit):
    got_value, got_unit, _ = _measure(text)
    assert (got_value, got_unit) == (value, unit)


@pytest.mark.parametrize(
    "text",
    [
        "10 (14) bar (psi)",  # 14 psi is not 10 bar: two quantities, not one
        "12 (3.6) mm (in)",  # 3.6 in is not 12 mm
        "20 (25) barg (barg)",  # the same unit twice with two values
        "340 (23.4) psig",  # one unit after two numbers: which number it belongs to is unknown
        "24.8 (109) m3/h",
        "5 (note 3) kW (hp)",
    ],
)
def test_a_cell_that_is_not_one_quantity_twice_is_read_exactly_as_before(text):
    assert dual_unit_form.first_system(text, datasheets.same_quantity_twice) is None
    assert _measure(text)[1] is None


def test_the_number_is_converted_in_the_first_unit():
    assert _measure("24.8 (109) m3/h (USGPM)")[2] == 24.8
    assert _measure("10 (145) bar (psi)")[2] == pytest.approx(1.0)


def _fact(name, raw, page=2):
    cols = datasheets.value_columns(raw, field_label=name)
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name,
        "field_value": raw,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": page,
        "equipment_tag": None,
        **cols,
    }


def test_the_unit_check_no_longer_says_a_printed_unit_is_missing():
    facts = [_fact("rated flow", "24.8 (109) m3/h (USGPM)")]
    pages = {2: "CAPACITY / FLOW 24.8 (109) m3/h (USGPM)"}
    found = [
        r
        for r in dc.evaluate(facts, equipment_type="Centrifugal Pump", page_texts=pages)
        if r["rule_id"] == "DS-U1"
    ]
    assert found == []


def test_a_value_with_no_unit_at_all_is_still_said_to_have_none():
    facts = [_fact("rated flow", "24.8")]
    pages = {2: "CAPACITY / FLOW 24.8"}
    found = [
        r
        for r in dc.evaluate(facts, equipment_type="Centrifugal Pump", page_texts=pages)
        if r["rule_id"] == "DS-U1"
    ]
    assert len(found) == 1 and "without a unit" in found[0]["detail"]
