"""#1619: a value shaped like a tag or grade, a letter then a minus then digits, was read as a
negative number by parse_value. A minus directly after a letter joins; it is no sign, so the
reading is None (the same rule the en dash and the Unicode hyphens already follow), and a real
negative stays negative. Invented values only.
"""

from __future__ import annotations

import pytest

from app import (
    claims,
    comparison,
    datasheet_checks,
    impossible_sign,
    numparse,
    requirements_3b,
    rule_eval,
)

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


#: The generated grid: an unreadable value in each clause form a sentence can hide it in.
CLAUSES = [
    "The temperature shall not exceed 40 C, except pumps which shall be {} C or lower",
    "The temperature shall not exceed 40 C, except for pumps, which shall be {} C or lower",
    "The temperature shall not exceed 40 C, except pumps that are {} C or lower",
    "The temperature shall not exceed 40 C, other than pumps at {} C or lower",
    "The temperature shall be 40 C or lower, except pumps which shall be {} C or lower",
    "The temperature shall not exceed 40 C unless the pump is {} C or lower",
    "The temperature shall not exceed 40 C if the pump is {} C or lower",
    "Where the pump is {} C or lower, the temperature shall not exceed 40 C",
    "The temperature shall be between 10 C and 40 C, except pumps at {} C or lower",
]
JOINED = ["MDMT-", "A1-", "Zone 2-", "3-", "5--", "T", "\u00b1", ".", "P-", "A--", "a,"]
EXCEPTION_GRID = [
    clause.format(joined + number)
    for clause in CLAUSES
    for joined in JOINED
    for number in ("15", "29")
]


def _subject_verdict(text: str, value: str, subject: str) -> str:
    limit = requirements_3b.parse_limit_or_range(text)
    requirement = {
        **(limit or {}),
        "id": "r",
        "clause": "1",
        "requirement_type": requirements_3b.classify(text, limit),
        "requirement_text": text,
        "source_text": text,
        "field": "design temperature",
        "exceptions": requirements_3b.parse_exceptions(text),
    }
    fact = {
        "id": "f",
        "field_name": "design temperature",
        "field_label": "Design temperature",
        "field_value": f"{value} C",
        "raw_value": value,
        "raw_unit": "C",
        "is_blank": 0,
        "blank_marker": None,
    }
    return comparison.compare(requirement, fact, subject=subject)["status"]


@pytest.mark.parametrize("subject", ["pumps", "valves", None])
@pytest.mark.parametrize("value", ["-40", "10", "39", "100"])
@pytest.mark.parametrize("text", EXCEPTION_GRID)
def test_an_unreadable_exception_sends_the_requirement_to_review(text, value, subject):
    assert _subject_verdict(text, value, subject) == comparison.NEEDS_ENGINEER_REVIEW


def test_a_later_unreadable_limit_refuses_a_readable_first_one():
    assert requirements_3b.parse_limit("5 C or lower, A-15 C or lower") is None


@pytest.mark.parametrize(
    "exception, value, subject, expected",
    [
        ("-15", "10", "pumps", comparison.NON_COMPLIANT),
        ("15", "10", "pumps", comparison.COMPLIANT),
        ("15", "20", "pumps", comparison.NON_COMPLIANT),
        ("15", "20", "valves", comparison.COMPLIANT),
    ],
)
def test_a_readable_exception_still_decides(exception, value, subject, expected):
    text = f"The temperature shall not exceed 40 C, except pumps which shall be {exception} C or lower"
    assert _subject_verdict(text, value, subject) == expected


# ------------------------------------------------------------- a size is not a tag


@pytest.mark.parametrize(
    "text",
    [
        "for 1/2 in or larger",
        "for 2-1/2 in or larger",
        "for 2 1/2 in or larger",
        "NPS 3/4 in or larger",
        "The temperature shall not exceed 40 C for 1/2 in or larger",
    ],
)
def test_a_fraction_gives_no_limit_and_goes_to_review(text):
    assert requirements_3b.parse_limit(text) is None
    assert requirements_3b.parse_limit_or_range(text) is None
    assert _verdict(text, "1", "in") == comparison.NEEDS_ENGINEER_REVIEW


@pytest.mark.parametrize("text", ["10/5 mm or less", "12/25/2019 mm or less"])
def test_an_improper_fraction_or_a_date_is_refused(text):
    assert requirements_3b.parse_limit(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "A-1/2 in or larger",
        "T1/2 in or larger",
        "-1/2 in or less",
        "10-12 mm or larger",
    ],
)
def test_a_glued_fraction_or_a_digit_range_stays_in_review(text):
    assert requirements_3b.parse_limit(text) is None


# ----------------------------------------------- a glued number is held, not passed

GLUED = ["A-5", "T-5", "PN-16", "PN\u221216"]


def _sheet_fact(name, value, unit=None):
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": 2,
        "equipment_tag": None,
    }


def _item(item_id):
    for checklist in datasheet_checks.load_rules()["checklists"].values():
        for item in checklist.get("items", []) if isinstance(checklist, dict) else []:
            if item["id"] == item_id:
                return item
    raise AssertionError(item_id)


@pytest.mark.parametrize("value", GLUED)
def test_glued_number_is_no_number(value):
    assert numparse.has_joining_minus(value)
    assert numparse.parse_value(value) is None


@pytest.mark.parametrize(
    "value", ["-5", "T = -5", "T -5", "5", "Fire", "", None, "10-12"]
)
def test_glued_number_is_not_a_real_negative_or_a_word(value):
    assert not numparse.has_joining_minus(value)


@pytest.mark.parametrize(
    "item_id, field, role",
    [("PSV-01", "set pressure", "set_pressure"), ("PSV-02", "mawp", "mawp")],
)
@pytest.mark.parametrize("value", GLUED)
def test_glued_number_required_item_is_held(value, item_id, field, role):
    rules = datasheet_checks.load_rules()
    fact = _sheet_fact(field, value)
    item_result = datasheet_checks.evaluate_item(
        _item(item_id), {role: [fact]}, {}, None, rules, draft=False
    )
    assert item_result["status"] == "COMPLIANT", (
        "the check alone accepts a stated value"
    )
    held = impossible_sign.hold_results([item_result], [fact], rules, frozenset())
    assert held[0]["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "cannot be read as a number" in held[0]["detail"]
    assert "negative" not in held[0]["detail"]


@pytest.mark.parametrize("value", GLUED)
def test_glued_number_is_held_on_a_library_pass(value):
    verdict = {"status": "COMPLIANT", "rationale": "within the limit"}
    fact = {"field_name": "built up back pressure", "raw_value": value, "is_blank": 0}
    assert (
        impossible_sign.hold_pass(verdict, fact)["status"]
        == comparison.NEEDS_ENGINEER_REVIEW
    )
    assert impossible_sign.hold_pass({**verdict, "status": "NON_COMPLIANT"}, fact)[
        "status"
    ] == ("NON_COMPLIANT")


@pytest.mark.parametrize("value", GLUED)
def test_glued_number_is_left_alone_where_a_negative_is_real(value):
    verdict = {"status": "COMPLIANT", "rationale": "within the limit"}
    fact = {"field_name": "design pressure", "raw_value": value, "is_blank": 0}
    assert impossible_sign.hold_pass(verdict, fact)["status"] == "COMPLIANT"


@pytest.mark.parametrize("value", GLUED)
def test_implausible_flags_a_glued_number_on_a_bounded_role(value):
    rules = datasheet_checks.load_rules()
    fact = _sheet_fact("specific heat ratio", value)
    doubt = datasheet_checks.implausible(fact, "specific_heat_ratio", rules)
    assert doubt is not None and "cannot be read as a number" in doubt


def test_implausible_leaves_a_word_alone():
    rules = datasheet_checks.load_rules()
    fact = _sheet_fact("specific heat ratio", "Fire")
    assert datasheet_checks.implausible(fact, "specific_heat_ratio", rules) is None
