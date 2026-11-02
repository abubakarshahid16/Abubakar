"""#1619: a value shaped like a tag or grade, a letter then a minus then digits, was read as a
negative number by parse_value. A minus directly after a letter joins; it is no sign, so the
reading is None (the same rule the en dash and the Unicode hyphens already follow), and a real
negative stays negative. Invented values only.
"""

from __future__ import annotations

import pytest

from app import claims, comparison, numparse, requirements_3b, rule_eval

U_MINUS = chr(0x2212)


@pytest.mark.parametrize("minus", ["-", U_MINUS, chr(0xFE63), chr(0xFF0D)])
@pytest.mark.parametrize("text", ["A{}5", "P{}101", "xy{}29", "Z{}1,5", "μ{}5"])
def test_a_minus_directly_after_a_letter_is_no_sign(text, minus):
    assert numparse.parse_value(text.format(minus)) is None


@pytest.mark.parametrize("text", ["T--5", "A_-5", "A.-5", "A/-5", "%-5", "+-5", "--5"])
def test_no_sign_outside_the_sign_leads(text):
    assert numparse.parse_value(text) is None


@pytest.mark.parametrize("minus", ["-", U_MINUS])
def test_a_tag_shaped_value_has_no_measurement_value(minus):
    measured = claims.normalise(f"A{minus}5", "mm")
    assert measured.normalized_value is None
    assert measured.raw_value == f"A{minus}5"


@pytest.mark.parametrize("minus", ["-", U_MINUS])
@pytest.mark.parametrize(
    "text",
    [
        "{}5",
        " {}5 ",
        "T = {}5",
        "T={}5",
        "T: {}5",
        "T {}5",
        "< {}5",
        "<{}5",
        "({}5",
        "≤{}5",
    ],
)
def test_a_real_negative_stays_negative(text, minus):
    assert numparse.parse_value(text.format(minus)) == pytest.approx(-5.0)


@pytest.mark.parametrize("minus", ["-", U_MINUS])
def test_a_real_negative_with_a_unit_stays_negative(minus):
    assert claims.normalise(f"{minus}5", "C").normalized_value == pytest.approx(-5.0)
    for sentence in (f"The minimum is {minus}5 C.", f"T = {minus}5 C"):
        found = claims.extract_measurements(sentence)
        assert [m.raw_value for m in found] == ["-5"]
        assert claims.normalise(
            found[0].raw_value, "C"
        ).normalized_value == pytest.approx(-5.0)


def test_a_comparator_word_keeps_its_negative_value():
    measured = claims.normalise("not less than -5", "C")
    assert measured.comparator == ">=" and measured.normalized_value == pytest.approx(
        -5.0
    )


def test_find_numbers_reads_no_sign_on_a_hyphen_after_a_letter():
    assert [(n.value, n.sign) for n in numparse.find_numbers("A-5")] == [(5.0, "+")]


def test_the_number_gates_keep_a_typographic_minus_after_a_letter():
    """Keeps the sign the page printed: 29 must not pass a gate on a source saying U+2212 29."""
    source = f"MDMT{U_MINUS}29 C"
    assert numparse.number_keys(source) == {-29.0}
    assert rule_eval.verify_numbers({"rows": [{"from": -29.0}]}, source)
    assert not rule_eval.verify_numbers({"rows": [{"from": 29.0}]}, source)


@pytest.mark.parametrize(
    "text, value",
    [
        (f"{U_MINUS}5", -5.0),
        (f"T = {U_MINUS}5", -5.0),
        (f"T={U_MINUS}5", -5.0),
        ("T = -5", -5.0),
    ],
)
def test_find_numbers_keeps_the_other_readings(text, value):
    assert numparse.find_numbers(text)[-1].value == value


def test_a_tag_in_a_sentence_is_no_measurement():
    assert claims.extract_measurements("Grade A-5 mm is listed.") == ()


def test_the_stated_figure_is_not_found_in_a_tag_as_a_negative():
    assert not numparse.value_in_text("-5", f"Grade A{U_MINUS}5 applies")
    assert not numparse.value_in_text("-5", "Grade A-5 applies")


#: Every case the three review rounds of #1635 found: no reading of the value is safe.
NO_LIMIT = [
    ("Grade A-5 mm or less applies.", "mm"),
    ("MDMT-29 C or lower", "C"),
    ("Grade A-15 C or lower", "C"),
    ("P-101 mm or less", "mm"),
    ("A-5.5 mm or less", "mm"),
    ("A-1,5 mm or less", "mm"),
    ("5mm-10 mm or less", "mm"),
    ("A1-29 C or lower", "C"),
    ("Zone 2-29 C or lower", "C"),
    ("No.2-29 C or lower", "C"),
    ("150-29 C or lower", "C"),
    ("T1-15 C or lower", "C"),
    ("Item 3-15 C or lower", "C"),
    ("3-5 mm or less", "mm"),
    ("-20--10 C or lower", "C"),
    ("5--10 C or lower", "C"),
    ("A--29 C or lower", "C"),
    ("Zone 2--29 C or lower", "C"),
    ("T--5 C or lower", "C"),
    ("T5 C or lower", "C"),
    ("a,5 C or lower", "C"),
]

#: A refused first value must not let a later one in the same sentence decide.
TWO_LIMITS = [
    ("MDMT-29 C or lower, 40 C or lower", "C"),
    ("3-5 C or lower; 40 C or lower", "C"),
    ("T5 mm or more, 10 mm or less", "mm"),
    ("A-15 C or lower, 2 C or higher", "C"),
    ("MDMT-29 C or lower, between 10 C and 40 C", "C"),
    ("MDMT-29 C or lower, and shall be 40 C", "C"),
]

#: (text, unit, the value read). A real negative or positive keeps its value.
REAL_LIMIT = [
    ("The design value is -5 C or less.", "C", "-5"),
    ("-5 C or less", "C", "-5"),
    ("-20 - -10 C or lower", "C", "-10"),
    ("T=-29 C or lower", "C", "-29"),
    ("T = -29 C or lower", "C", "-29"),
    ("T: -29 C or lower", "C", "-29"),
    ("(-15 C or lower", "C", "-15"),
    ("3 -5 C or lower", "C", "-5"),
    ("The design value is 5 C or less.", "C", "5"),
    ("The design value is +5 C or less.", "C", "+5"),
    ("The thickness is 1,5 mm or less.", "mm", "1,5"),
]


def _verdict(text: str, value: str, unit: str) -> str:
    limit = requirements_3b.parse_limit_or_range(text)
    requirement = {
        **(limit or {}),
        "id": "r",
        "clause": "1",
        "requirement_type": requirements_3b.classify(text, limit),
        "requirement_text": text,
        "source_text": text,
        "field": "design temperature",
    }
    fact = {
        "id": "f",
        "field_name": "design temperature",
        "field_label": "Design temperature",
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "is_blank": 0,
        "blank_marker": None,
    }
    return comparison.compare(requirement, fact)["status"]


@pytest.mark.parametrize("text, unit", NO_LIMIT)
def test_a_joined_number_gives_no_trailing_limit(text, unit):
    assert requirements_3b.parse_limit(text) is None


@pytest.mark.parametrize("value", ["-40", "0", "5", "25"])
@pytest.mark.parametrize("text, unit", NO_LIMIT)
def test_a_joined_number_goes_to_review(text, unit, value):
    assert _verdict(text, value, unit) == comparison.NEEDS_ENGINEER_REVIEW


@pytest.mark.parametrize("text, unit, raw", REAL_LIMIT)
def test_real_limits_keep_their_value(text, unit, raw):
    assert requirements_3b.parse_limit(text)["raw_value"] == raw


@pytest.mark.parametrize(
    "text, unit, raw", [r for r in REAL_LIMIT if r[2].startswith("-")]
)
def test_real_negative_limits_still_decide(text, unit, raw):
    assert _verdict(text, "25", unit) == comparison.NON_COMPLIANT
    assert _verdict(text, "-40", unit) == comparison.COMPLIANT


@pytest.mark.parametrize("text, unit", TWO_LIMITS)
def test_two_limits_a_refused_first_value_gives_no_limit(text, unit):
    assert requirements_3b.parse_limit(text) is None
    assert requirements_3b.parse_limit_or_range(text) is None


@pytest.mark.parametrize("value", ["-40", "-5", "0", "5", "25", "100"])
@pytest.mark.parametrize("text, unit", TWO_LIMITS)
def test_two_limits_go_to_review(text, unit, value):
    assert _verdict(text, value, unit) == comparison.NEEDS_ENGINEER_REVIEW


def test_two_readable_limits_still_read_the_first():
    assert (
        requirements_3b.parse_limit("5 C or lower, 40 C or lower")["raw_value"] == "5"
    )


def test_a_candidate_with_no_direction_does_not_refuse():
    limit = requirements_3b.parse_limit("A-5 mm or so, 40 C or lower")
    assert limit is not None and limit["raw_value"] == "40"


def test_a_refused_limit_is_no_field_comparison():
    text = "The outlet pressure shall not exceed the inlet pressure, A-5 mm or less"
    assert requirements_3b.parse_cross_field(text) is None
    assert requirements_3b.parse_limit_or_range(text) is None
