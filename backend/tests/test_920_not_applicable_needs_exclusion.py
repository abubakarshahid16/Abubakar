"""#920 (PF2): a clause is excused as not applicable only when the stated value
names ANOTHER member of a family the condition's own term belongs to. Services
and equipment kinds are not all mutually exclusive: a sour hydrocarbon stream
is both, a vessel stands in a hazardous area. Invented data only."""
from __future__ import annotations

import pytest

from app import conditions


def _fact(name, value):
    return {"id": f"f-{name}", "field_name": name, "field_label": name, "field_value": value, "page": 1,
            "extraction_method": "extracted", "is_blank": 0, "document_id": "doc_sheet"}


@pytest.mark.parametrize("shape, condition, field, value", [
    (conditions.SHAPE_SERVICE, "pumps in sour service", "service", "Hydrocarbon"),
    (conditions.SHAPE_SERVICE, "pumps in hydrocarbon service", "service", "Sour"),
    (conditions.SHAPE_SERVICE, "pumps in hydrocarbon service", "fluid", "Crude oil"),
    (conditions.SHAPE_SERVICE, "pumps in seawater service", "service", "Fire water"),
    (conditions.SHAPE_CLASS, "equipment in a hazardous area", "equipment type", "Pressure vessel"),
    (conditions.SHAPE_CLASS, "equipment in zone 2", "equipment type", "Centrifugal pump"),
    (conditions.SHAPE_CLASS, "offshore pumps", "area", "Zone 1"),
])
def test_a_value_from_another_family_does_not_excuse_the_clause(shape, condition, field, value):
    gate = conditions._evaluate_terms(shape, condition, [_fact(field, value)])
    assert gate["state"] == conditions.UNKNOWN, gate
    assert gate["evidence"] is None


@pytest.mark.parametrize("shape, condition, field, value", [
    (conditions.SHAPE_SERVICE, "pumps in hydrocarbon service", "service", "Potable water"),
    (conditions.SHAPE_SERVICE, "pumps in sour service", "service", "Sweet"),
    (conditions.SHAPE_CLASS, "equipment in zone 1", "area", "Zone 2"),
    (conditions.SHAPE_CLASS, "onshore pumps", "area", "Offshore"),
    (conditions.SHAPE_MATERIAL, "carbon steel systems", "shell material", "Stainless steel 316L"),
])
def test_a_value_from_the_same_family_still_excuses_it_and_says_what(shape, condition, field, value):
    gate = conditions._evaluate_terms(shape, condition, [_fact(field, value)])
    assert gate["state"] == conditions.NOT_SATISFIED, gate
    assert gate["evidence"]["field_name"] == field
