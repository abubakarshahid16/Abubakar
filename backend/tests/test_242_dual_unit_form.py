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
        "24.8 (30) m3/h (USGPM)",  # 30 USGPM is not 24.8 m3/h: two quantities (planner's review)
        # a bracket that is a NOTE (gauge, normal, kg, rpm), never a second system
        "10 (12) bar (g)",
        "5 (7) m3/h (n)",
        "10 (-2) bar (kg)",
        "6 (2) VEFV (pcs)",  # the word after the numbers is not a unit: a tag, not a quantity
        # cloud's review: the second bracket is checked too, it must be a unit
        "10 (20) kW (max)",  # a rate and its qualifier, not two systems
        "10 (20) kW (min)",  # "min" is a unit (minutes) but not of kW's kind
        "10 (20) m3/h (min)",  # a different dimension from a flow
        "5 (7) bar (normal)",
    ],
)
def test_a_cell_that_is_not_one_quantity_twice_is_read_exactly_as_before(text):
    assert dual_unit_form.first_system(text, datasheets.same_quantity_twice) is None
    assert _measure(text)[1] is None


def test_a_us_gallon_rate_converts_so_the_two_halves_are_checked_not_trusted():
    from app import claims

    assert claims.unit_dimension("usgpm") == "volumetric_flow"
    assert claims.normalise("109", "USGPM").normalized_value == pytest.approx(
        24.757, rel=1e-3
    )
    assert (
        claims.normalise("1", "usgpm").normalized_value
        == claims.normalise("1", "usgal/min").normalized_value
    )


@pytest.mark.parametrize(
    "text, unit",
    [
        ("24.8 m3/h (109 USGPM)", "m3/h"),
        ("10 barg (145 psig)", "barg"),
        (
            "20 barg (25 barg)",
            "barg",
        ),  # one unit twice: not two systems, read as before
        (
            "20 barg (40 barg)",
            "barg",
        ),  # far apart, but one unit twice is not two systems
        ("120 m3/h (approx)", "m3/h"),
        # nominal conversions are roundings, not a second quantity (s3's review)
        ("10 bar (150 psi)", "bar"),
        ("12 mm (0.5 in)", "mm"),
        ("150 C (302 F)", "C"),
    ],
)
def test_the_trailing_form_that_agrees_or_is_no_second_system_is_read_as_before(
    text, unit
):
    assert _measure(text)[1] == unit


@pytest.mark.parametrize("text", ["24.8 m3/h (30 USGPM)", "10 bar (14 psi)"])
def test_the_trailing_form_with_two_different_quantities_is_refused_not_guessed(text):
    assert _measure(text) == (None, None, None)


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
