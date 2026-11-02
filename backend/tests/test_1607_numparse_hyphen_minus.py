"""#1607: parse_value read a Unicode hyphen before a number as a plus: U+2010 and U+2011 are
what a word processor prints for a hyphen-minus, and that spelling of 0.5 came back as +0.5, a wrong
sign. They now follow the en dash's rule: a minus where the value begins or after whitespace
or a comparator; glued to a letter or inside a range the text cannot say, so None.
Invented values only.
"""

from __future__ import annotations

import pytest

from app import claims, numparse

HYPHEN, NON_BREAKING = chr(0x2010), chr(0x2011)
BOTH = [HYPHEN, NON_BREAKING]


@pytest.mark.parametrize("h", BOTH)
@pytest.mark.parametrize(
    "tail, expected", [("0.5", -0.5), ("5", -5.0), ("1,5", -1.5), ("1,200", -1200.0)]
)
def test_a_unicode_hyphen_starting_a_value_is_a_minus(h, tail, expected):
    assert numparse.parse_value(h + tail) == pytest.approx(expected)


@pytest.mark.parametrize("h", BOTH)
def test_after_a_comparator_it_is_a_minus(h):
    assert numparse.parse_value(f"< {h}5") == pytest.approx(-5.0)
    assert numparse.parse_value(f"<{h}5") == pytest.approx(-5.0)


@pytest.mark.parametrize("h", BOTH)
@pytest.mark.parametrize("text", ["T{}29", "10{}12", "{} 29"])
def test_glued_to_a_letter_in_a_range_or_apart_the_text_cannot_say(h, text):
    assert numparse.parse_value(text.format(h)) is None


@pytest.mark.parametrize("h", BOTH)
def test_parse_value_and_as_number_agree_on_the_sign(h):
    assert numparse.parse_value(h + "0.5") == numparse.as_number(h + "0.5")


@pytest.mark.parametrize("h", BOTH)
def test_the_measurement_keeps_the_minus(h):
    measured = claims.normalise(h + "0.5", "barg")
    assert measured is not None and measured.normalized_value < 0


@pytest.mark.parametrize(
    "text, expected", [("-0.5", -0.5), ("0.5", 0.5), (chr(0x2013) + "0.5", -0.5)]
)
def test_the_other_spellings_do_not_move(text, expected):
    assert numparse.parse_value(text) == pytest.approx(expected)
