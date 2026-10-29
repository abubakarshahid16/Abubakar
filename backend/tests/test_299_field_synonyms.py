"""Order 299.1 (spelling): relief-valve quantities in `reference/field_synonyms.json`, the one table every pairing
folds both sides with. Invented sheet labels only; no database, no model."""

from __future__ import annotations

import json
from collections import defaultdict

import pytest

from app import comparison, field_links

GROUPS = json.loads(field_links.SYNONYMS_PATH.read_text(encoding="utf-8"))["groups"]


def test_every_spelling_of_every_group_folds_to_its_groups_name():
    for name, spellings in GROUPS.items():
        for spelling in [name, *spellings]:
            assert field_links.canonical(spelling) == field_links._fold(name), (
                name,
                spelling,
            )


def test_no_spelling_belongs_to_two_groups():
    owners = defaultdict(set)
    for name, spellings in GROUPS.items():
        for spelling in [name, *spellings]:
            owners[field_links._fold(spelling)].add(field_links._fold(name))
    assert {s: o for s, o in owners.items() if len(o) > 1} == {}


@pytest.mark.parametrize(
    "label, canonical",
    [
        ("Set Press.", "set pressure"),
        ("Relieving Temp", "relieving temperature"),
        ("Built-up Backpressure", "built up back pressure"),
        ("Super-imposed back pressure", "superimposed back pressure"),
        ("Over-pressure", "overpressure"),
        ("Blow down", "blowdown"),
        ("Cold Differential Set Pressure", "cdtp"),
        ("Required relieving capacity", "required capacity"),
        ("Vapour density", "vapor density"),
        ("Volume flow rate", "volumetric flow rate"),
        ("MDMT", "minimum design metal temperature"),
        ("Back pressure - constant", "constant superimposed back pressure"),
        ("Variable back press.", "variable superimposed back pressure"),
        ("Superimposed back pressure variable", "variable superimposed back pressure"),
        ("Max. allow. working pressure", "mawp"),
        ("Back pressure, built-up", "built up back pressure"),
    ],
)
def test_a_relief_valve_label_in_another_spelling_folds_to_the_quantity(
    label, canonical
):
    assert field_links.canonical(label) == canonical


@pytest.mark.parametrize(
    "label",
    [
        "Reset pressure",
        "Set pressure tolerance",
        "Inlet pressure",
        "Upset press",
        "Relieving temperature rise",
    ],
)
def test_a_longer_or_different_name_is_not_swallowed_by_a_new_group(label):
    """Whole words only: "reset press" is not "set press", and "set pressure tolerance" stays its own quantity."""
    folded = field_links.canonical(label)
    assert folded != "set pressure" and folded != "relieving temperature"


def _req(subject):
    text = f"The {subject} shall not exceed 30 bar."
    return {
        "id": "r1",
        "standard_document_id": "doc_std",
        "requirement_type": "numeric_limit",
        "operator": "<=",
        "raw_value": "30",
        "raw_unit": "bar",
        "value": 3000000.0,
        "subject": subject,
        "clause": "4.1",
        "requirement_text": text,
        "source_text": text,
    }


def _fact(name):
    return {
        "id": f"f-{name}",
        "document_id": "doc_sheet",
        "submittal_document_id": "doc_sheet",
        "field_name": name,
        "field_value": "25 bar",
        "raw_value": "25",
        "raw_unit": "bar",
        "value": 2500000.0,
        "is_blank": 0,
        "page": 1,
        "extraction_method": "extracted",
        "equipment_tag": None,
    }


def test_a_sheet_label_in_a_short_form_meets_the_clauses_full_name():
    row = _fact("Relieving Press.")
    match = comparison.match_by_containment(_req("relieving pressure"), [row])
    assert match["fact"] is row


def test_a_different_quantity_still_does_not_pair():
    row = _fact("Set Press.")
    match = comparison.match_by_containment(_req("relieving pressure"), [row])
    assert match["fact"] is None


def test_a_label_naming_both_constant_and_variable_is_not_folded_to_either_quantity():
    """Two quantities in one label stay unmapped: a pairing would pick one and drop the other."""
    folded = field_links.canonical("Back pressure constant / variable")
    assert folded not in (
        "constant superimposed back pressure",
        "variable superimposed back pressure",
    )
