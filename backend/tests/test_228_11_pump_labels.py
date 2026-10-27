"""Order 228.11: the spellings a pump datasheet prints for two checklist fields.

On the 35B run of the M-03 pump sheet the reader read every page, but the
checklist still said "Rated flow was not found" and "Operating temperature was
not found": the sheet prints "CAPACITY / FLOW" and "PUMPING TEMPERATURE", and
the data knew neither spelling, so the contractor was asked for values the
sheet gives. The spellings are the field's, whole label only. Invented values.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import form_reader_fields as ff
from app.datasheets import normalise_field_name

PUMP = "Centrifugal Pump"


def fact(name, value, unit):
    return {
        "id": f"f-{name}",
        "field_name": normalise_field_name(name),
        "field_label": name,
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": 2,
        "equipment_tag": None,
    }


@pytest.mark.parametrize(
    ("label", "role"),
    [
        ("CAPACITY / FLOW", "rated_flow"),
        ("Flow/Capacity", "rated_flow"),
        ("Rated capacity / flow", "rated_flow"),
        ("PUMPING TEMPERATURE", "operating_temperature"),
        ("Normal pumping temperature", "operating_temperature"),
    ],
)
def test_the_spellings_a_pump_sheet_prints_name_the_field(label, role):
    assert dc.role_of(normalise_field_name(label), dc.load_rules()) == role


@pytest.mark.parametrize(
    "label", ["Capacity", "Pumping temperature (max)", "Flow", "Pumping"]
)
def test_a_looser_label_is_still_not_the_field(label):
    assert dc.role_of(normalise_field_name(label), dc.load_rules()) is None


def test_a_stored_pump_sheet_fact_is_not_reported_missing():
    facts = [
        fact("CAPACITY / FLOW", "24.8", "m3/h"),
        fact("PUMPING TEMPERATURE", "76.7", "C"),
    ]
    results = dc.evaluate(facts, equipment_type=PUMP, page_texts={2: "x"})
    said = " ".join(r["detail"] for r in results if r["rule_id"] == "DS-M1")
    assert "Rated flow was not found" not in said
    assert "Operating temperature was not found" not in said


def test_the_reader_is_asked_with_the_pump_labels():
    fields = {f.key: f for f in ff.field_list_for(PUMP)}
    assert "capacity / flow" in fields["rated_flow"].synonyms
    assert "pumping temperature" in fields["operating_temperature"].synonyms
    prompt = ff.build_prompt([fields["rated_flow"]], "x", 1)
    assert "capacity / flow" in prompt


def test_the_printed_label_is_found_on_the_page_text():
    rules = dc.load_rules()
    pages = {1: "x", 2: "7 CAPACITY / FLOW 24.8 m3/h\n8 PUMPING TEMPERATURE 76.7 C"}
    assert dc.label_search("rated_flow", rules, pages) == [2]
    assert dc.label_search("operating_temperature", rules, pages) == [2]
