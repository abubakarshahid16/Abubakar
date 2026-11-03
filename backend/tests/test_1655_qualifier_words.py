"""#1655: a bound or approximation word before a number ("up to", "approx.", "NLT") does not make
it a label's number: `parse_value` reads the value as it did before #1640, while a label ("Note",
"Class", "Zone") still reads no number. Invented values only."""

from __future__ import annotations

import pytest

from app import (  # noqa: F401  (config hands numparse its comparator list)
    claims,
    config,
    numparse,
)


@pytest.mark.parametrize(
    "text",
    [
        "up to 10",
        "Up To 10",
        "over 10",
        "under 10",
        "below 10",
        "above 10",
        "about 10",
        "approx 10",
        "approx. 10",
        "approximately 10",
        "nominal 10",
        "nom. 10",
        "typ. 10",
        "typical 10",
        "NLT 10",
        "NMT 10",
        "equal to 10",
        "ca. 10",
    ],
)
def test_a_qualifier_word_reads_the_value(text):
    assert numparse.parse_value(text) == 10.0


@pytest.mark.parametrize(
    "text", ["approx. max 10", "up to max 10", "max approx 10", "nominal min 10"]
)
def test_a_qualifier_beside_a_comparator_reads_the_value_leading_and_trailing(text):
    assert numparse.parse_value(text) == 10.0


@pytest.mark.parametrize(
    "text",
    [
        "Note up to 5",
        "Class over 150",
        "Zone below 2",
        "Note approx. 5",
        "Item nominal 3",
        "Note 5",
        "Class 150",
        "approx.5",
        "up to5",
    ],
)
def test_a_label_before_or_among_qualifiers_reads_no_number(text):
    assert numparse.parse_value(text) is None


def test_a_qualifier_keeps_a_real_negative_and_a_glued_minus_stays_none():
    assert numparse.parse_value("below -10") == -10.0
    assert numparse.parse_value("approx.-10") is None


def test_a_qualifier_word_is_no_comparator():
    # The comparator list of `claims` is unchanged: "approx" gives no operator, only a readable value.
    assert (
        claims.parse_comparator("approx") is None
        and claims.parse_comparator("up to") is None
    )
