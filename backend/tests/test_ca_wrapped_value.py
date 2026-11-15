"""Two readings of one text value that wraps over two lines are a CONFLICT, never a silent merge (R74b: the wrapped-value merge was removed; it merged nothing on the live
copy and could only ever hide a conflict, and a conflict holds every verdict on the field until an engineer decides). Invented values; no database, no model."""

from __future__ import annotations

import pytest

from app import datasheet_ai as ai
from app import datasheets as ds


def _fact(value, **over):
    return {
        "is_blank": False,
        "raw_value": None,
        "normalized_value": None,
        "normalized_unit": None,
        "field_value": value,
        "field_label": "Shell material",
        **over,
    }


@pytest.mark.parametrize(
    ("reading", "stored"),
    [
        ("SA 999 Gr 7N", "SA 999 Gr 7M"),  # two real grades
        ("Carbon steel", "Stainless steel"),
        ("No", "Not required"),
        ("SS 316", "SS 316L"),
        ("4-28 cP", "4-28 cP By Contractor"),
        ("5 bar", "5 bar max"),
        ("12 barg", "12 barg 14 barg"),
        ("Yes", "Yes (see note)"),
        ("Carbon steel", "Carbon steel clad with stainless steel"),
        ("Hot dip galvanised", "Hot dip galvanised only inside"),
        ("Material A", "Material A with Material B"),
        ("Class 150", "Class 150 RF"),
        ("Stainless steel", "Stainless steel 316L"),
        (
            "SA 999 Gr 7N",
            "SA 999 Gr 7N + Internal Coating",
        ),  # the first line alone, and the second line alone, of one wrapped value
        ("+ Internal Coating", "SA 999 Gr 7N + Internal Coating"),
        (
            "76.7 (170)",
            "OC ( OF)\n\n76.7 (170)",
        ),  # a header over the value, either way round
        ("OC ( OF)\n\n76.7 (170)", "76.7 (170)"),
    ],
)
def test_two_different_or_wrapped_readings_stay_a_conflict(reading, stored):
    assert ds._geometry_agrees(reading, False, _fact(stored)) is False


def test_the_same_value_still_agrees_and_the_merge_of_the_readers_keeps_a_difference_as_a_conflict():
    assert ds._geometry_agrees("SA 999 Gr 7N", False, _fact("SA 999 Gr 7N")) is True
    rule = {
        "id": "r1",
        "page": 1,
        "field_label": "Shell material",
        "field_name": "shell material",
        "raw_value": None,
        "field_value": "SA 999 Gr 7N + Internal Coating",
        "is_blank": False,
        "normalized_value": None,
        "normalized_unit": None,
        "value_column": None,
    }
    reading = {
        "page": 1,
        "field": "Shell material",
        "field_name": "shell material",
        "value": "SA 999 Gr 7N",
        "unit": None,
        "quote": "q",
        "kind": "offered",
    }
    assert [d["outcome"] for d in ai.merge_readings([rule], [reading])] == [ai.CONFLICT]
    assert [
        d["outcome"]
        for d in ai.merge_readings(
            [rule], [{**reading, "value": "SA 999 Gr 7N + Internal Coating"}]
        )
    ] == [ai.AGREED]
