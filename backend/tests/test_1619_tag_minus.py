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


@pytest.mark.parametrize(
    "text",
    [
        "Grade A-5 mm or less applies.",
        "MDMT-29 C or lower",
        "Grade A-15 C or lower",
        "P-101 mm or less",
        "A-5.5 mm or less",
        "A-1,5 mm or less",
        "5mm-10 mm or less",
    ],
)
def test_a_trailing_limit_never_restarts_inside_a_joined_number(text):
    assert requirements_3b.parse_limit(text) is None


@pytest.mark.parametrize(
    "text, raw", [("-5 C or less", "-5"), ("5 C or less", "5"), ("+5 C or less", "+5")]
)
def test_a_trailing_limit_keeps_a_real_value(text, raw):
    limit = requirements_3b.parse_limit("The design value is " + text + ".")
    assert limit is not None and limit["raw_value"] == raw


@pytest.mark.parametrize(
    "text",
    [
        "A1-29 C or lower",
        "Zone 2-29 C or lower",
        "No.2-29 C or lower",
        "150-29 C or lower",
        "T1-15 C or lower",
        "Item 3-15 C or lower",
        "3-5 mm or less",
    ],
)
def test_a_digit_then_hyphen_then_digit_is_no_trailing_limit(text):
    assert requirements_3b.parse_limit(text) is None


@pytest.mark.parametrize(
    "text, value, unit, expected",
    [
        ("MDMT-29 C or lower", "5", "C", comparison.NEEDS_ENGINEER_REVIEW),
        ("MDMT-29 C or lower", "-40", "C", comparison.NEEDS_ENGINEER_REVIEW),
        ("A1-29 C or lower", "5", "C", comparison.NEEDS_ENGINEER_REVIEW),
        ("3-5 mm or less", "4", "mm", comparison.NEEDS_ENGINEER_REVIEW),
    ],
)
def test_an_unreadable_limit_goes_to_review(text, value, unit, expected):
    limit = requirements_3b.parse_limit(text)
    requirement = {
        "id": "r",
        "clause": "1",
        "requirement_type": requirements_3b.classify(text, limit),
        "operator": (limit or {}).get("operator"),
        "raw_value": (limit or {}).get("raw_value"),
        "raw_unit": (limit or {}).get("raw_unit"),
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
    assert comparison.compare(requirement, fact)["status"] == expected
