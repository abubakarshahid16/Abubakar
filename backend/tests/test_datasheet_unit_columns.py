"""A unit printed in its OWN cell, and the unit vocabulary that decides it.

Found by the datasheet benchmark (2026-09-30), three generic defects:

  1. the shared unit vocabulary (`claims.is_unit`) refused real engineering
     units - per-time rates (kg/h, t/h, Nm3/h, m3/d), `ms`, weeks, months,
     `kPa(g)` - so the AI gate dropped them and the rules reader kept the
     number and lost the unit; a random word must still be refused;
  2. a workbook / Word row `Flow | m3/h | 42` was read as the value
     "m3/h 42", which parses as no number at all;
  3. (merge, `test_datasheet_ai.py`).

Every value is made up (fixture conventions). Mutations: M1740-M1759
(`scripts/mutations/datasheet_units.py`).
"""

from __future__ import annotations

import pytest

from app import claims, claude_datasheet, datasheets, geometry_reader, match_rules
from app import datasheet_inputs as di
from tests.test_datasheet_inputs import (  # noqa: F401 - the autouse fixture
    _extract, _facts, _ingest_office, _xlsx, flag_on, temp_storage)

# ====================================================== 1. the vocabulary

RATES = ["kg/h", "kg/hr", "t/h", "Nm3/h", "Sm3/h", "Sm3/d", "m3/d", "mm/y",
         "W/cm2", "kN/m", "kJ/kg", "l/h"]
TIMES = ["ms", "weeks", "months", "week"]
REFERENCED = ["kPa(g)", "bar (a)", "MPag", "kg/cm2 (g)"]
NOT_UNITS = ["banana", "N/A", "N/S", "T/C", "I/O", "a/b", "kg/banana",
             "banana/h", "kg/m2/h", "Design pressure (a)", "Class", ""]


@pytest.mark.parametrize("unit", RATES)
def test_a_compound_rate_is_a_unit(unit):
    assert claims.is_unit(unit), unit
    assert claims.is_rate_unit(unit), unit


@pytest.mark.parametrize("unit", TIMES)
def test_time_and_calendar_units_are_units(unit):
    assert claims.is_unit(unit), unit


@pytest.mark.parametrize("unit", REFERENCED)
def test_a_pressure_with_its_reference_is_a_unit(unit):
    assert claims.is_unit(unit), unit


@pytest.mark.parametrize("word", NOT_UNITS)
def test_a_word_is_still_not_a_unit(word):
    assert not claims.is_unit(word), word
    assert not claude_datasheet._unit_recognised(word), word


def test_a_superscript_is_printing_not_identity():
    assert claims.is_unit("m³/h") and claims.is_unit("W/m²")


def test_calendar_durations_carry_no_dimension_and_ms_is_a_time():
    """A month is not a fixed number of hours; `ms` is a time like `s`."""
    assert claims.unit_dimension("ms") == "time"
    assert claims.unit_dimension("weeks") is None
    assert claims.unit_dimension("months") is None


def test_the_ai_gate_keeps_a_rate_and_refuses_a_word():
    page = "Required capacity 5400 kg/h\nDelivery 16 weeks\nRange 25 banana"
    proposals = [
        {"field": "Required capacity", "value": "5400", "unit": "kg/h",
         "quote": "Required capacity 5400 kg/h", "kind": "required"},
        {"field": "Delivery", "value": "16", "unit": "weeks",
         "quote": "Delivery 16 weeks", "kind": "offered"},
        {"field": "Range", "value": "25", "unit": "banana",
         "quote": "Range 25 banana", "kind": "offered"},
    ]
    out = claude_datasheet.accept(proposals, page)
    assert [p["field"] for p in out["accepted"]] == ["Required capacity", "Delivery"]
    assert out["counts"] == {claude_datasheet.Reason.UNIT_UNRECOGNISED.value: 1}


def test_the_match_rule_unit_guard_reads_the_same_vocabulary():
    """Rule 8: `match_rules` asked the raw spelling set directly and so
    refused a rate the grammar knows."""
    requirement = {"raw_unit": "C"}
    assert not match_rules.unit_dimension_conflict(requirement, {"raw_unit": "kg/h"})
    assert match_rules.unit_dimension_conflict(requirement, {"raw_unit": "banana"})


def test_the_geometry_reader_unit_label_reads_the_same_vocabulary():
    assert geometry_reader.is_unit_label("kg/h")
    assert geometry_reader.is_unit_label("ms")
    assert not geometry_reader.is_unit_label("banana")
    # A single letter is still only a unit where one is expected.
    assert not geometry_reader.is_unit_label("N")
    assert geometry_reader.is_unit_label("N", allow_single=True)


def test_a_rate_value_parses_with_its_unit():
    """The rules reader: "8000 Nm3/h" keeps its unit now that it is one."""
    number, unit, _m = datasheets.measure_value("8000 Nm3/h")
    assert number == "8000" and unit == "Nm3/h"


# ====================================================== 2. the unit cell

def test_a_unit_cell_before_the_value_goes_after_it():
    pairs = di.pairs_from_rows([("Capacity", "m3/h", "42"),
                                ("Required capacity", "5400", "kg/h")])
    assert pairs == [("Capacity", "42 m3/h"), ("Required capacity", "5400 kg/h")]
    number, unit, _m = datasheets.measure_value(pairs[0][1])
    assert number == "42" and unit == "m3/h"


def test_a_header_units_column_names_the_unit_even_one_the_vocabulary_lacks():
    """`cP` is not in the vocabulary; the sheet's own "Unit" header says it
    is the unit. Columns count the printed cells, row numbers included."""
    rows = [("No", "Item", "Unit", "Value"),
            ("1", "Viscosity", "cP", "3"),
            ("2", "Operating range", "bar", "0 - 40")]
    assert di.pairs_from_rows(rows) == [("Viscosity", "3 cP"),
                                        ("Operating range", "0 - 40 bar")]


def test_one_value_cell_under_a_unit_header_stays_the_value():
    rows = [("Item", "Unit", "Value"), ("Pumped fluid", "Water"),
            ("Head", "m", "60")]
    assert di.pairs_from_rows(rows) == [("Pumped fluid", "Water"), ("Head", "60 m")]


def test_a_blank_beside_a_unit_is_the_blank_alone():
    assert di.pairs_from_rows([("Impeller diameter", "mm", "By Vendor")]) == \
        [("Impeller diameter", "By Vendor")]


def test_a_gauge_unit_cell_keeps_its_reference():
    assert di.pairs_from_rows([("Design pressure", "kPa(g)", "12")]) == \
        [("Design pressure", "12 kPa(g)")]


def test_two_unit_cells_are_ambiguous_and_nothing_moves():
    assert di.pairs_from_rows([("Flow", "m3/h", "kg/h", "42")]) == \
        [("Flow", "m3/h kg/h 42")]


def test_a_workbook_with_a_unit_column_before_the_value_becomes_facts(tmp_path, flag_on):
    def book(wb):
        ws = wb.active
        ws.title = "DS-0001"
        ws.append(["Item", "Unit", "Value"])
        ws.append(["Capacity", "m3/h", 42])
        ws.append(["Steam flow", "kg/h", 1234])
    doc = _ingest_office(_xlsx(tmp_path / "ds.xlsx", book), "doc_units")
    _extract(doc)
    by = {f["field_name"]: f for f in _facts(doc)}
    assert by["capacity"]["raw_value"] == "42" and by["capacity"]["raw_unit"] == "m3/h"
    assert by["steam flow"]["raw_value"] == "1234" and by["steam flow"]["unit"] == "kg/h"
