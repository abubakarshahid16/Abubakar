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
            "76.7 (170)",
            "OC ( OF)\n\n76.7 (170)",
        ),  # the same value under a unit header: the reading is the shorter one
        (
            "Mat X Gr Y",
            "Header Junk Mat X Gr Y",
        ),  # a header the first line carried, no scope word in it
    ],
)
def test_a_shorter_reading_that_is_the_start_or_end_of_the_stored_value_and_adds_no_meaning_agrees(
    reading, stored
):
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
        # R74 M4: words that change what the value MEANS were merged silently before
        ("Carbon steel", "Carbon steel clad with stainless steel"),
        ("Hot dip galvanised", "Hot dip galvanised only inside"),
        ("Material A", "Material A with Material B"),
        ("Class 150", "Class 150 RF"),
        ("Stainless steel", "Stainless steel 316L"),
        ("Carbon steel", "Carbon steel lined"),
        ("Painted", "Painted except the nozzles"),
        (
            "SA 999 Gr 7N",
            "SA 999 Gr 7N + Internal Coating",
        ),  # a scope word (internal): a question for the engineer, not a merge
        ("+ Internal Coating", "SA 999 Gr 7N + Internal Coating"),
    ],
)
def test_two_different_values_stay_different(reading, stored):
    assert ds._geometry_agrees(reading, False, _fact(stored)) is False


def test_a_merge_never_loses_words_the_longer_reading_is_never_the_one_that_agrees():
    """Whichever reader wrote first: the reading that would be DROPPED as a duplicate must be the shorter one. A longer reading against a shorter stored value is a conflict."""
    assert (
        ds._geometry_agrees("OC ( OF)\n\n76.7 (170)", False, _fact("76.7 (170)"))
        is False
    )
    assert (
        ds._geometry_agrees("76.7 (170)", False, _fact("OC ( OF)\n\n76.7 (170)"))
        is True
    )


def test_the_merge_of_the_readers_calls_a_wrapped_reading_agreed_and_a_true_difference_a_conflict():
    rule = {
        "id": "r1",
        "page": 1,
        "field_label": "Shell material",
        "field_name": "shell material",
        "raw_value": None,
        "field_value": "Header Junk Mat X Gr Y",
        "is_blank": False,
        "normalized_value": None,
        "normalized_unit": None,
        "value_column": None,
    }
    same = {
        "page": 1,
        "field": "Shell material",
        "field_name": "shell material",
        "value": "Mat X Gr Y",
        "unit": None,
        "quote": "q",
        "kind": "offered",
    }
    other = {**same, "value": "Mat X Gr Z"}
    longer = {**same, "value": "Header Junk Mat X Gr Y Extra Words"}
    assert [d["outcome"] for d in ai.merge_readings([rule], [same])] == [ai.AGREED]
    assert [d["outcome"] for d in ai.merge_readings([rule], [other])] == [ai.CONFLICT]
    assert [d["outcome"] for d in ai.merge_readings([rule], [longer])] == [ai.CONFLICT]
