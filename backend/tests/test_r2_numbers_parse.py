"""Round-2 number-reading fixes N1, N2, N3, N5, N6 (invented names only).

Every test here fails when its fix is removed: see scripts/mutations/r2_numbers.py
(M1990-M1999).
"""

from __future__ import annotations

import pytest

from app import claims, comparison, datasheets


# ----------------------------------------------------------------- N1 signs
@pytest.mark.parametrize("text,expected", [
    ("−29", -29.0),            # U+2212 minus
    ("− 29", -29.0),           # normalised, then "- 29"? see below
])
def test_unicode_minus_is_negative(text, expected):
    if " " in text:
        # a minus separated from its digits is ambiguous, not positive
        assert claims.parse_value(text) is None
    else:
        assert claims.parse_value(text) == expected


@pytest.mark.parametrize("text", ["–29", "—29", "≤ –29"])
def test_a_dash_directly_before_digits_at_start_is_a_minus(text):
    assert claims.parse_value(text) == -29.0


@pytest.mark.parametrize("text", ["29–343", "29 – 343", "T–29", "– 29", "- 29"])
def test_an_ambiguous_dash_is_none_never_positive(text):
    assert claims.parse_value(text) is None


def test_the_minus_survives_normalise():
    m = claims.normalise("−29", "C")
    assert m.normalized_value == -29.0


def test_datasheet_cell_with_unicode_minus_is_read_negative():
    value, unit, measurement = datasheets.measure_value("−29 C")
    assert (value, unit) == ("-29", "C")
    assert measurement.normalized_value == -29.0


# ----------------------------------------------------- N2 whitespace groups
@pytest.mark.parametrize("text", ["34 3", "5 10", "1 2 3", "1234 567", "12  345", "1 20"])
def test_digit_groups_that_are_not_thousands_are_none(text):
    assert claims.parse_value(text) is None


@pytest.mark.parametrize("text,expected", [("1 200", 1200.0), ("12 345 678", 12345678.0),
                                           ("12 345,5", 12345.5)])
def test_strict_space_thousands_are_read(text, expected):
    assert claims.parse_value(text) == expected


# ----------------------------------------------------------- N3 EU thousands
@pytest.mark.parametrize("text", ["4.000", "1.200", "12.345", "-4.000", "<= 4.000"])
def test_three_decimals_is_ambiguous_none(text):
    assert claims.parse_value(text) is None


@pytest.mark.parametrize("text,expected", [
    ("1,200", 1200.0), ("3,0", 3.0), ("3.5", 3.5), ("6.89", 6.89),
    ("0.125", 0.125), ("1234.567", 1234.567), ("3,600", 3600.0), ("1,200.5", 1200.5),
])
def test_unambiguous_shapes_keep_their_value(text, expected):
    assert claims.parse_value(text) == expected


def test_ambiguous_fact_goes_to_engineer_review_not_a_verdict():
    requirement = {"requirement_type": "numeric_limit", "operator": "<=",
                   "raw_value": "3,600", "raw_unit": "rpm", "value": 3600.0,
                   "unit": "rpm", "subject": "speed", "requirement_text": "<= 3,600 rpm",
                   "source_text": "Speed shall not exceed 3,600 rpm.", "field": "speed",
                   "exceptions": []}
    fact = {"id": "f1", "field_name": "speed", "field_value": "4.000 rpm",
            "raw_value": "4.000", "raw_unit": "rpm", "is_blank": 0, "page": 1}
    assert comparison.compare(requirement, fact)["status"] == comparison.NEEDS_ENGINEER_REVIEW


# ----------------------------------------------------- N5 name tolerance
def _req(subject, unit="dB(A)", **over):
    base = {"requirement_type": "numeric_limit", "value": 85.0, "unit": unit,
            "raw_value": "85", "raw_unit": unit, "subject": subject}
    return {**base, **over}


def _fact(name, unit="dB(A)", **over):
    base = {"id": f"fact-{name}", "field_name": name, "raw_value": "90",
            "raw_unit": unit, "unit": unit}
    return {**base, **over}


@pytest.mark.parametrize("subject,name,unit", [
    ("Noise", "Noise level", "dB(A)"),
    ("Maximum operating temperature", "Max operating temperature", "C"),
    ("Maximum operating pressure", "Max operating press", "bar"),
    ("Inside dia", "Inside diameter", "mm"),
])
def test_abbreviation_and_generic_word_tolerance(subject, name, unit):
    result = comparison.match_by_containment(_req(subject, unit), [_fact(name, unit)])
    assert result["fact"] is not None and result["fact"]["field_name"] == name


def test_unrelated_names_do_not_match():
    result = comparison.match_by_containment(
        _req("Noise"), [_fact("Vibration level"), _fact("Motor rating")])
    assert result["fact"] is None


def test_tolerant_match_still_needs_a_compatible_unit():
    # name matches after normalisation, but a length is never paired with a pressure
    result = comparison.match_by_containment(
        _req("Maximum operating temperature", "C"),
        [_fact("Max operating temperature", "bar")])
    assert result["fact"] is None


def test_tolerant_match_does_not_run_in_reverse():
    # "Pressure" must not claim "Design pressure"
    result = comparison.match_by_containment(
        _req("Pressure", "bar"), [_fact("Design pressure", "bar")])
    assert result["fact"] is None


def test_max_does_not_match_min():
    result = comparison.match_by_containment(
        _req("Minimum operating temperature", "C"),
        [_fact("Max operating temperature", "C")])
    assert result["fact"] is None


# ------------------------------------------------------- N6 compound units
@pytest.mark.parametrize("sentence,raw_unit,dimension", [
    ("Vibration shall not exceed 3.0 mm/s.", "mm/s", "velocity"),
    ("Peak velocity is 4.5 in/s.", "in/s", "velocity"),
    ("Flow is 50 m3/h.", "m3/h", "volumetric_flow"),
    ("Feed rate is 100 kg/h.", "kg/h", "mass_flow"),
])
def test_compound_units_parse_whole(sentence, raw_unit, dimension):
    (m,) = claims.extract_measurements(sentence)
    assert m.raw_unit == raw_unit
    assert m.dimension == dimension
    assert m.normalized_value is not None


def test_dba_with_brackets_is_whole_and_same_as_dba():
    (a,) = claims.extract_measurements("Noise shall not exceed 85 dB(A).")
    (b,) = claims.extract_measurements("Noise shall not exceed 85 dBA.")
    assert a.raw_unit == "dB(A)"
    assert claims.same_unit(a, b)


def test_unknown_compound_unit_is_no_measurement_not_a_truncated_base():
    assert claims.extract_measurements("Rate is 5 widgets/s.") == ()
    assert claims.extract_measurements("Rate is 5 mm/fortnight.") == ()


def test_speed_is_never_a_length():
    (m,) = claims.extract_measurements("Vibration shall not exceed 3.0 mm/s.")
    assert m.dimension != "length"
    assert claims.unit_dimension("in/s") == claims.unit_dimension("mm/s")
    assert claims.normalise("4.5", "in/s").normalized_value == pytest.approx(114.3)


def test_existing_units_unchanged():
    (m,) = claims.extract_measurements("Thickness shall be at least 280 um.")
    assert (m.raw_unit, m.normalized_value) == ("um", 280.0)
    (g,) = claims.extract_measurements("Pressure is 3 kPa(g).")
    assert g.raw_unit == "kPa"


def test_datasheet_range_with_unicode_minus_keeps_its_sign():
    assert datasheets.parse_range("−29 to 343 C") == ("-29", "343", "C")


def test_tolerant_match_needs_units_both_stated_and_alike():
    # kg and rpm are both "recognised, no dimension": match_rules lets that pair
    # through, so the tolerant route's own unit gate is what stops it.
    assert comparison.match_by_containment(
        _req("Maximum operating speed", "kg"), [_fact("Max operating speed", "rpm")])["fact"] is None
    assert comparison.match_by_containment(
        _req("Maximum operating speed", "rpm"), [_fact("Max operating speed", "")])["fact"] is None
    assert comparison.match_by_containment(
        _req("Maximum operating speed", "rpm"), [_fact("Max operating speed", "rpm")])["fact"] is not None


def test_l_per_min_is_read_whole_but_not_converted():
    (m,) = claims.extract_measurements("Flow is 50 L/min.")
    assert m.raw_unit == "L/min" and m.normalized_value is None
