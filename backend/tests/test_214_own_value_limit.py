"""Order 214: a reference that states its own value is a plain limit.

"Set pressure shall not exceed the vessel MAWP of 12 barg" was read as a
comparison with another field (the MAWP), the 12 barg dropped, and the clause
went to an engineer as "MAWP is not stated on the datasheet". It is a limit of
12 barg. Invented sentences only.
"""
from __future__ import annotations

import pytest

from app import requirements_3b as r3b


def test_a_reference_with_its_own_value_is_a_plain_limit():
    sentence = "The set pressure shall not exceed the vessel MAWP of 12 barg."
    limit = r3b.parse_limit(sentence)
    assert (limit["operator"], limit["raw_value"], limit["raw_unit"]) == ("<=", "12", "barg")
    assert r3b.parse_cross_field(sentence) is None  # not a comparison with another field
    assert r3b.parse_limit_or_range(sentence)["operator"] == "<="


def test_a_minimum_with_its_own_value_reads_the_right_way():
    limit = r3b.parse_limit("The wall thickness shall be at least the minimum thickness of 6 mm.")
    assert (limit["operator"], limit["raw_value"], limit["raw_unit"]) == (">=", "6", "mm")


@pytest.mark.parametrize("sentence", [
    # a phrase that picks one of several values is not one limit
    "The wall thickness shall be at least the lesser of 10 mm or 6 mm.",
    # a second number follows: not one value
    "The wall thickness shall be not less than the minimum thickness of 6 mm or 8 mm.",
    # a reference with no number stays a comparison with another field
    "The set pressure shall not exceed the maximum allowable working pressure of the vessel.",
])
def test_unclear_phrases_are_not_turned_into_a_limit(sentence):
    assert r3b.parse_limit(sentence) is None


def test_a_reference_without_a_number_is_still_a_comparison_with_another_field():
    sentence = "The set pressure shall not exceed the maximum allowable working pressure of the vessel."
    assert r3b.parse_cross_field(sentence) is not None


def test_a_unit_the_system_cannot_convert_is_left_alone():
    # kg/s is not a unit the comparison converts yet: keep the old route
    # (an engineer reads it) rather than store a limit it cannot compare.
    assert r3b.parse_limit("The relieving capacity shall be at least the required capacity of 5 kg/s.") is None
