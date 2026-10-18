"""#889 (Stage C, PF2, part of #882): a limit written with a SPACE as the
thousands separator keeps its thousands and its unit.

"shall not exceed 25 000 hours" was stored as the limit 25 with no unit: the
value regex stopped at the space and "000" is not a unit token. The rule is
generic (CLAUDE.md rule 13): groups after the first must be exactly three
digits each, and a recognised unit must follow at once. A number that merely
stands next to another number ("between 20 and 80", "items 4 5 and 6",
"pages 4 5", "Class 150 300") is never joined.

Each test here fails on the code before the fix (checked by hand: the value
came back "25", the unit None).
"""
from __future__ import annotations

import pytest

from app import requirements_3b


@pytest.mark.parametrize("sentence, raw_value, raw_unit, value", [
    ("The design life shall not exceed 25 000 hours.", "25 000", "hours", 25000.0),
    ("The plate thickness shall be at least 1 250 mm.", "1 250", "mm", 1250.0),
    ("The design pressure shall not exceed 10 000 kPa.", "10 000", "kPa", 10000.0),
    # NBSP and narrow no-break space are what a PDF usually emits for the gap.
    ("The design life shall not exceed 25\u00a0000 hours.", "25\u00a0000", "hours", 25000.0),
    ("The run shall not exceed 12 345 678 mm.", "12 345 678", "mm", 12345678.0),
])
def test_space_grouped_limit_keeps_thousands_and_unit(sentence, raw_value, raw_unit, value):
    limit = requirements_3b.parse_limit(sentence)
    assert limit is not None
    assert limit["raw_value"] == raw_value
    assert limit["raw_unit"] == raw_unit
    # The printed number, read through the one parser: the full figure.
    assert requirements_3b.claims.parse_value(limit["raw_value"]) == value
    assert limit["unit"] is not None


def test_space_grouped_limit_normalises_through_the_unit_table():
    limit = requirements_3b.parse_limit("The design pressure shall not exceed 10 000 kPa.")
    assert (limit["value"], limit["unit"]) == (10.0, "MPa")
    limit = requirements_3b.parse_limit("The design life shall not exceed 25 000 hours.")
    assert (limit["value"], limit["unit"]) == (25000.0, "h")


def test_space_grouped_decimal_keeps_its_fraction():
    limit = requirements_3b.parse_limit("The span shall not exceed 1 250,5 mm.")
    assert limit["raw_value"] == "1 250,5" and limit["raw_unit"] == "mm"
    assert requirements_3b.claims.parse_value(limit["raw_value"]) == 1250.5


@pytest.mark.parametrize("sentence, raw_value", [
    # A list word after the second group: two numbers.
    ("The class shall not exceed 150 300 and 600.", "150"),
    # A third number next: never joined.
    ("Pressure shall not exceed 150 300 500 and 600 bar.", "150"),
    # End of the sentence with no unit: left as it was before #889.
    ("The pressure class shall not exceed 150 300.", "150"),
    # A second group that is not three digits is another number.
    ("The count shall not exceed 25 00 items.", "25"),
    ("The count shall not exceed 25 0000 bar.", "25"),
    # A word that is not a unit does not join the groups.
    ("The count shall not exceed 25 000 widgets.", "25"),
])
def test_separate_numbers_are_not_joined(sentence, raw_value):
    limit = requirements_3b.parse_limit(sentence)
    assert limit is not None
    assert limit["raw_value"] == raw_value


def test_list_and_page_numbers_stay_separate():
    # "items 4 5 and 6": the limit is the 10 bar, not a joined 456.
    limit = requirements_3b.parse_limit_or_range("Items 4 5 and 6 shall not exceed 10 bar.")
    assert (limit["raw_value"], limit["raw_unit"]) == ("10", "bar")
    limit = requirements_3b.parse_limit_or_range("Pages 4 5 state a maximum of 90 dB(A).")
    assert (limit["raw_value"], limit["raw_unit"]) == ("90", "dB(A)")
    # A range of two separate numbers is still a range of two numbers.
    span = requirements_3b.parse_limit_or_range("The opening shall be between 20 and 80 %.")
    assert (span["value_low"], span["value_high"]) == (20.0, 80.0)
    assert requirements_3b.parse_limit("The class shall be Class 150 300.") is None


def test_comma_and_dot_handling_unchanged():
    # #1050 / #616: a comma after a leading zero is a decimal, "3,300" is 3300.
    assert requirements_3b.claims.parse_value("0,030") == 0.03
    assert requirements_3b.claims.parse_value("3,300") == 3300.0
    limit = requirements_3b.parse_limit("The roughness shall not exceed 0,030 mm.")
    assert (limit["raw_value"], limit["raw_unit"], limit["value"]) == ("0,030", "mm", 30.0)  # 30 um
    limit = requirements_3b.parse_limit("The capacity shall not exceed 3,300 kg.")
    assert (limit["raw_value"], limit["raw_unit"]) == ("3,300", "kg")
    assert requirements_3b.claims.parse_value(limit["raw_value"]) == 3300.0


def test_space_grouped_range_nominal_and_trailing_forms():
    span = requirements_3b.parse_range("The length shall be between 1 000 mm and 2 000 mm.")
    assert (span["value_low"], span["value_high"], span["raw_unit"]) == (1000.0, 2000.0, "mm")
    nominal = requirements_3b.parse_nominal("The design life shall be 25 000 hours.")
    assert (nominal["raw_value"], nominal["raw_unit"]) == ("25 000", "hours")
    assert (nominal["value_low"], nominal["value_high"]) == (24999.5, 25000.5)
    trailing = requirements_3b.parse_limit("The load shall be 1 500 kg or more.")
    assert (trailing["operator"], trailing["raw_value"], trailing["raw_unit"]) == (">=", "1 500", "kg")


def test_contradiction_tripwire_still_reads_a_grouped_value():
    sentence = "The design life shall not be less than 25 000 hours."
    limit = requirements_3b.parse_limit(sentence)
    assert limit["operator"] == ">=" and limit["raw_value"] == "25 000"
    assert not requirements_3b.contradicts_source(limit, sentence)
    assert requirements_3b.contradicts_source({**limit, "operator": "<="}, sentence)
