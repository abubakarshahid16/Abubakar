"""R27 (#830): the units the AI reader's readings were refused for.

Measured with the cloud reader on two real sheets (planner's runs, 12 Oct
2026): 12 readings were refused as "unit not recognised" - a viscosity in
centipoise, a gas flow in standard cubic feet per hour, and two-unit cells
("bar (psi)", "m3/h (USGPM)") the model gave as the sheet prints them. Each
value was read correctly and thrown away over its unit.

Now `cP` and `SCFH` are units (recognised, NOT converted), and the AI gate
takes a two-unit cell by the unit outside its brackets. A degree sign printed
as a letter ("OC") is still not provably a unit and stays refused.

Invented values only.
"""
from __future__ import annotations

import pytest

from app import claims, comparison, datasheets
from app import claude_datasheet as cd
from tests.test_claude_datasheet import _answer, _fact, temp_storage  # noqa: F401 - autouse

PAGE = """PUMP DATASHEET                                   Page 2 of 7
Viscosity at pumping temperature : 0.85 cP
Purge gas flow : 4500 SCFH
Rated differential pressure : 12.5 bar (psi)
Rated capacity : 60 m3/h (USGPM)
Seal flush rate : 3 widgets (psi)
Pumping temperature : 85 OC
"""


@pytest.mark.parametrize("unit, dimension", [("cP", "viscosity"), ("cp", "viscosity"), ("SCFH", None)])
def test_the_two_spellings_are_units_now(unit, dimension):
    assert claims.is_unit(unit) and claims.unit_dimension(unit) == dimension


def test_they_are_recognised_and_not_converted():
    """One spelling of its quantity each: no conversion is invented. A
    standard gas volume differs from a normal one by its reference
    conditions, so SCFH converts to nothing."""
    for unit in ("cP", "SCFH"):
        assert claims.normalise("1", unit).normalized_unit is None


def test_the_rule_readers_keep_the_unit_beside_the_number():
    assert datasheets.measure_value("0.85 cP")[:2] == ("0.85", "cP")
    assert datasheets.measure_value("4500 SCFH")[:2] == ("4500", "SCFH")


def _viscosity_limit(limit="5", unit="cP"):
    text = f"The viscosity shall not exceed {limit} {unit}."
    return {"id": "r", "standard_document_id": None, "requirement_type": "numeric_limit",
            "requirement_text": text, "source_text": text, "operator": "<=", "raw_value": limit,
            "raw_unit": unit, "field": "viscosity", "exceptions": [], "condition": None}


def _viscosity(value, unit="cP"):
    return {"id": "f", "document_id": None, "field_name": "viscosity", "field_label": "Viscosity",
            "field_value": f"{value} {unit}", "raw_value": value, "raw_unit": unit, "is_blank": 0,
            "blank_marker": None}


def test_two_values_in_the_same_spelling_are_compared():
    assert comparison.compare(_viscosity_limit(), _viscosity("0.85"))["status"] == comparison.COMPLIANT
    assert comparison.compare(_viscosity_limit(), _viscosity("12"))["status"] == comparison.NON_COMPLIANT


def test_a_viscosity_is_never_compared_with_another_quantity_or_another_spelling():
    """Not converted means not compared across spellings: no factor is assumed."""
    for unit in ("mPa.s", "bar", "SCFH"):
        verdict = comparison.compare(_viscosity_limit(unit=unit), _viscosity("0.85"))
        assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW, unit


@pytest.mark.parametrize("unit", ["cP", "SCFH", "bar (psi)", "m3/h (USGPM)", "bar a (psia)", "m (ft)"])
def test_the_ai_gate_takes_these_units(unit):
    assert cd._unit_recognised(unit)


@pytest.mark.parametrize("unit", ["widgets (psi)", "locations", "OC", "(psi)", "see note (bar)"])
def test_the_ai_gate_still_refuses_what_is_not_a_unit(unit):
    """A bracket does not make a unit: the part OUTSIDE it must be one. A
    degree sign printed as the letter O is not provably degrees."""
    assert not cd._unit_recognised(unit)


def test_readings_in_these_units_are_accepted_and_the_others_refused():
    facts = [_fact("Viscosity at pumping temperature", "0.85", "Viscosity at pumping temperature : 0.85 cP", unit="cP"),
             _fact("Purge gas flow", "4500", "Purge gas flow : 4500 SCFH", unit="SCFH"),
             _fact("Rated differential pressure", "12.5", "Rated differential pressure : 12.5 bar (psi)",
                   unit="bar (psi)"),
             _fact("Rated capacity", "60", "Rated capacity : 60 m3/h (USGPM)", unit="m3/h (USGPM)"),
             _fact("Seal flush rate", "3", "Seal flush rate : 3 widgets (psi)", unit="widgets (psi)"),
             _fact("Pumping temperature", "85", "Pumping temperature : 85 OC", unit="OC")]
    out = cd.read_page(PAGE, 2, [], lambda p: _answer(*facts))
    assert sorted(p["field"] for p in out["accepted"]) == [
        "Purge gas flow", "Rated capacity", "Rated differential pressure", "Viscosity at pumping temperature"]
    assert out["counts"] == {cd.Reason.UNIT_UNRECOGNISED.value: 2}
