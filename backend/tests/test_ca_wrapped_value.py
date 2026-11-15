"""One text value that wraps over two lines is read twice (the whole value, and one line alone): the readings are ONE value, not a conflict (owner, 16 Nov 2026; the
vessel's shell material). Two TRUE different values stay a conflict (#1814). Invented values; no database, no model."""

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
        (
            "+ Internal Coating",
            "SA 999 Gr 7N + Internal Coating",
        ),  # the second line alone
        ("SA 999 Gr 7N", "SA 999 Gr 7N + Internal Coating"),  # the first line alone
        ("SA 999 Gr 7N + Internal Coating", "+ Internal Coating"),  # either way round
        ("76.7 (170)", "OC ( OF)\n\n76.7 (170)"),  # the same value under a unit header
    ],
)
def test_the_two_lines_of_one_wrapped_value_agree(reading, stored):
    assert ds._geometry_agrees(reading, False, _fact(stored)) is True


@pytest.mark.parametrize(
    ("reading", "stored"),
    [
        ("SA 999 Gr 7N", "SA 999 Gr 7M"),  # two real grades
        ("Carbon steel", "Stainless steel"),
        ("No", "Not required"),
        ("SS 316", "SS 316L"),  # a longer token is another value
        (
            "4-28 cP",
            "4-28 cP By Contractor",
        ),  # a deferred-value marker on one side only
        ("5 bar", "5 bar max"),  # a bound on one side only
        ("12 barg", "12 barg 14 barg"),  # another figure
        ("Yes", "Yes (see note)"),  # one word alone is never enough
    ],
)
def test_two_different_values_stay_different(reading, stored):
    assert ds._geometry_agrees(reading, False, _fact(stored)) is False


def test_the_merge_of_the_readers_calls_a_wrapped_reading_agreed_and_a_true_difference_a_conflict():
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
    same = {
        "page": 1,
        "field": "Shell material",
        "field_name": "shell material",
        "value": "SA 999 Gr 7N",
        "unit": None,
        "quote": "q",
        "kind": "offered",
    }
    other = {**same, "value": "SA 999 Gr 7M"}
    assert [d["outcome"] for d in ai.merge_readings([rule], [same])] == [ai.AGREED]
    assert [d["outcome"] for d in ai.merge_readings([rule], [other])] == [ai.CONFLICT]
