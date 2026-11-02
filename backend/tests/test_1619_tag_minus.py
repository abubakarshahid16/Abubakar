"""#1619: a value shaped like a tag or grade, a letter then a minus then digits, was read as a
negative number by parse_value. A minus directly after a letter joins; it is no sign, so the
reading is None (the same rule the en dash and the Unicode hyphens already follow), and a real
negative stays negative. Invented values only.
"""

from __future__ import annotations

import pytest

from app import claims, numparse, requirements_3b

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
    ["{}5", " {}5 ", "T = {}5", "T={}5", "T: {}5", "T {}5", "< {}5", "<{}5", "({}5", "≤{}5"],
)
def test_a_real_negative_stays_negative(text, minus):
    assert numparse.parse_value(text.format(minus)) == pytest.approx(-5.0)


@pytest.mark.parametrize("minus", ["-", U_MINUS])
def test_a_real_negative_with_a_unit_stays_negative(minus):
    assert claims.normalise(f"{minus}5", "C").normalized_value == pytest.approx(-5.0)
    for sentence in (f"The minimum is {minus}5 C.", f"T = {minus}5 C"):
        found = claims.extract_measurements(sentence)
        assert [m.raw_value for m in found] == ["-5"]
        assert claims.normalise(found[0].raw_value, "C").normalized_value == pytest.approx(-5.0)


def test_a_comparator_word_keeps_its_negative_value():
    measured = claims.normalise("not less than -5", "C")
    assert measured.comparator == ">=" and measured.normalized_value == pytest.approx(-5.0)


@pytest.mark.parametrize("minus", ["-", U_MINUS])
def test_find_numbers_reads_no_sign_after_a_letter(minus):
    assert [(n.value, n.sign) for n in numparse.find_numbers(f"A{minus}5")] == [(5.0, "+")]
    assert numparse.number_keys(f"A{minus}5") == {5.0}


@pytest.mark.parametrize(
    "text, value",
    [(f"{U_MINUS}5", -5.0), (f"T = {U_MINUS}5", -5.0), ("T = -5", -5.0), (f"(9{U_MINUS}5", 5.0)],
)
def test_find_numbers_keeps_the_other_readings(text, value):
    assert numparse.find_numbers(text)[-1].value == value


@pytest.mark.parametrize("minus", ["-", U_MINUS])
def test_a_tag_in_a_sentence_is_no_measurement(minus):
    assert claims.extract_measurements(f"Grade A{minus}5 mm is listed.") == ()


def test_the_stated_figure_is_not_found_in_a_tag_as_a_negative():
    assert not numparse.value_in_text("-5", f"Grade A{U_MINUS}5 applies")
    assert not numparse.value_in_text("-5", "Grade A-5 applies")


def test_a_trailing_limit_does_not_take_a_tag_for_a_negative_limit():
    assert requirements_3b.parse_limit("Grade A-5 mm or less applies.") is None
    limit = requirements_3b.parse_limit("The design value is -5 C or less.")
    assert limit is not None and limit["raw_value"] == "-5" and limit["value"] == pytest.approx(-5.0)
