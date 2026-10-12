"""#616: a comma after a leading zero is a decimal mark, never a thousands
separator. "0,030" is 0.03, not 30. Mutations M2421-M2425."""
from __future__ import annotations

import pytest

from app import claims, numparse


@pytest.mark.parametrize("text,expected", [
    ("0,030", 0.03), ("0,5", 0.5), ("0,500", 0.5), ("-0,030", -0.03),
    ("+0,125", 0.125)])
def test_a_leading_zero_comma_is_a_decimal(text, expected):
    assert numparse.parse_value(text) == pytest.approx(expected)
    # The same in a decimal-comma document: the rule does not depend on it.
    assert numparse.parse_value(text, decimal_comma_document=True) == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("1,000", 1000.0), ("12,500", 12500.0), ("10,500", 10500.0),
    ("1,000,030", 1000030.0)])
def test_a_real_thousands_group_is_still_thousands(text, expected):
    assert numparse.parse_value(text) == expected


def test_find_numbers_reads_a_leading_zero_comma_as_a_decimal():
    values = [n.value for n in numparse.find_numbers("gap 0,030 mm, load 1,000 N, 0,5 bar")]
    assert values == [pytest.approx(0.03), 1000.0, pytest.approx(0.5)]


def test_the_figure_check_agrees_with_the_decimal_reading():
    assert numparse.value_in_text(0.03, "clearance 0,030 mm") is True
    assert numparse.value_in_text(30, "clearance 0,030 mm") is False


def test_fold_numbers_keeps_the_decimal_comma_after_a_zero():
    assert numparse.fold_numbers("0,030") == "0,030"
    assert numparse.fold_numbers("8,300 and 10,500") == "8300 and 10500"


def test_last_digit_precision_counts_the_decimals_of_a_leading_zero_comma():
    # 0,030 prints three decimals: half a unit of the last digit is 0.0005 mm.
    measurement = claims.normalise("0,030", "mm")
    assert claims._last_digit_half(measurement) == pytest.approx(0.0005 * 1000)  # in um


def test_three_decimal_dot_values_are_still_ambiguous_only_in_decimal_comma_documents():
    assert numparse.parse_value("3.175") == pytest.approx(3.175)
    assert numparse.parse_value("3.175", decimal_comma_document=True) is None
