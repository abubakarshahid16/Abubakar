"""#1640 and #1653: a number is a value only where the text shows it is one. Invented values only.

#1640. A label ending in a number read as that number ("A5", "A+5", "Note 5", "Class 150", "PN16"),
a dash kept apart from its digits read as no sign ("Zone 2 - 29 C or lower", "A- 29", "A-(29"), a
Unicode minus after a comparator let `_LIMIT` skip to a later limit, and a minus that folding made a
hyphen ("MDMT" U+2212 "29" stored as "MDMT-29") let 29 pass a gate. Each now reads None and goes to
an engineer; a real negative keeps its sign. Nothing here knows a label's spelling (rule 13): the
labels below are generated shapes, and the tests say what a COMPARATOR is, never what a label is.

#1653. A reader's unit must sit with its number in the quote: value 10 and unit MPa are not proved
by "10 bar and 5 MPa".

The cases are generated (prefix x dash x number x ending), not picked one by one.
"""

from __future__ import annotations

import itertools

import pytest

from app import (
    ai_requirements,
    claims,
    claude_datasheet,
    comparison,
    compiled_rule_proof,
    datasheet_ai,
    datasheet_checks,
    form_reader,
    impossible_sign,
    numparse,
    reader_api,
    requirements_3b,
    rule_eval,
    standards_converter,
    unit_tie,
)
from app.form_reader_fields import Field

U_MINUS = "\u2212"
EN_DASH = "\u2013"

# --------------------------------------------------------------- generated value shapes

#: Words or marks that are no comparator, generated: a letter, letters, a word, a glued mark.
LABELS = [
    "A",
    "A+",
    "A ",
    "Ab ",
    "Abc ",
    "Abcd ",
    "AB",
    "AB ",
    "Ab Cd ",
    "Abc 2 ",
    "#",
    ".",
    ",",
    "Ab. ",
    "x",
    "the value is ",
]
#: Comparators of the one vocabulary (`claims._COMPARATOR_WORDS`) and the symbols that bind a value.
COMPARATORS = [
    "",
    "max ",
    "max. ",
    "maximum ",
    "min ",
    "min. ",
    "minimum of ",
    "at least ",
    "at most ",
    "not less than ",
    "not more than ",
    "<= ",
    "<",
    "≤",
    "≥ ",
    ">= ",
    "= ",
    "~",
    "(",
    "[",
    "Ab = ",
    "Ab=",
    "Ab: ",
    "Ab Cd: ",
    "±",
]
NUMBERS = ["5", "29", "5.5", "150", "1,200", "0,5", "16"]
SIGNS = ["", "-", U_MINUS, EN_DASH, "+"]


def _value(number: str) -> float:
    return float(
        number.replace(",", "") if number == "1,200" else number.replace(",", ".")
    )


LABEL_VALUES = [p + s + n for p, s, n in itertools.product(LABELS, SIGNS, NUMBERS)]


@pytest.mark.parametrize("text", LABEL_VALUES)
def test_a_label_number_reads_no_number(text):
    assert numparse.parse_value(text) is None
    assert claims.parse_value(text) is None


@pytest.mark.parametrize(
    "text", [t for t in LABEL_VALUES if not t.startswith("Abc 2 ")]
)
def test_a_label_number_is_known_as_one(text):
    # "Abc 2 5" holds two numbers: words to `parse_value`, as on main.
    assert numparse.has_label_number(text) or numparse.has_joining_minus(text)


@pytest.mark.parametrize(
    "prefix, sign, number",
    [
        c
        for c in itertools.product(COMPARATORS, SIGNS, NUMBERS)
        if not (c[0] == "\u00b1" and c[1])
    ],
)
def test_a_comparator_or_a_binding_symbol_keeps_the_number_and_its_sign(
    prefix, sign, number
):
    expected = -_value(number) if sign in ("-", U_MINUS, EN_DASH) else _value(number)
    assert numparse.parse_value(prefix + sign + number) == pytest.approx(expected)
    assert not numparse.has_label_number(prefix + sign + number)


def test_unset_comparator_vocabulary_reads_no_word(monkeypatch):
    monkeypatch.setattr(numparse, "COMPARATOR_PHRASE", None)
    assert numparse.parse_value("max 5") is None
    assert numparse.parse_value("<= 5") == 5.0


# ------------------------------------------------------------------- through the verdict


def _fact(value: str, unit: str = "C") -> dict:
    return {
        "id": "f",
        "field_name": "design temperature",
        "field_label": "Design temperature",
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "is_blank": 0,
        "blank_marker": None,
    }


def _requirement(text: str) -> dict:
    limit = requirements_3b.parse_limit_or_range(text)
    return {
        **(limit or {}),
        "id": "r",
        "clause": "1",
        "requirement_type": requirements_3b.classify(text, limit),
        "requirement_text": text,
        "source_text": text,
        "field": "design temperature",
        "exceptions": requirements_3b.parse_exceptions(text),
    }


LIMITS = [
    "The temperature shall not exceed 10 C",
    "The temperature shall be at least 3 C",
    "The temperature shall not exceed -20 C",
    "The temperature shall be at least -40 C",
    "The temperature shall not exceed 160 C",
]


@pytest.mark.parametrize("text", LIMITS)
@pytest.mark.parametrize("value", LABEL_VALUES)
def test_a_label_number_goes_to_review(text, value):
    assert (
        comparison.compare(_requirement(text), _fact(value))["status"]
        == comparison.NEEDS_ENGINEER_REVIEW
    )


@pytest.mark.parametrize(
    "text, value, status",
    [
        ("The temperature shall not exceed 10 C", v, s)
        for v, s in [
            ("5", "COMPLIANT"),
            ("max 5", "COMPLIANT"),
            ("<= 5", "COMPLIANT"),
            ("Ab = 5", "COMPLIANT"),
            ("15", "NON_COMPLIANT"),
            ("min 15", "NON_COMPLIANT"),
        ]
    ]
    + [
        ("The temperature shall not exceed -20 C", v, s)
        for v, s in [
            ("-29", "COMPLIANT"),
            (f"{U_MINUS}29", "COMPLIANT"),
            ("Ab = -29", "COMPLIANT"),
            ("29", "NON_COMPLIANT"),
        ]
    ],
)
def test_comparator_values_keep_their_verdict(text, value, status):
    assert comparison.compare(_requirement(text), _fact(value))["status"] == status


# --------------------------------------------------------------------------- the holds

HELD_LABELS = [
    p + n for p, n in itertools.product(["Ab ", "A", "A+", "Abc 2 "], ["5", "1,5"])
]


@pytest.mark.parametrize("value", HELD_LABELS)
def test_a_label_number_is_held_on_a_never_negative_role(value):
    verdict = {"status": "COMPLIANT", "rationale": "within the limit"}
    fact = {"field_name": "built up back pressure", "raw_value": value, "is_blank": 0}
    held = impossible_sign.hold_pass(verdict, fact)
    assert held["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "cannot be read as a number" in held["rationale"]
    rules = datasheet_checks.load_rules()
    item = next(
        i
        for c in rules["checklists"].values()
        if isinstance(c, dict)
        for i in c.get("items", [])
        if i["id"] == "PSV-01"
    )
    sheet = {
        **_fact(value, "barg"),
        "field_name": "set pressure",
        "field_label": "Set pressure",
        "page": 1,
    }
    result = datasheet_checks.evaluate_item(
        item, {"set_pressure": [sheet]}, {}, None, rules, draft=False
    )
    assert result["status"] == "COMPLIANT", "the check alone accepts a stated value"
    assert impossible_sign.hold_results([result], [sheet], rules, frozenset())[0][
        "status"
    ] == (comparison.NEEDS_ENGINEER_REVIEW)


@pytest.mark.parametrize("value", HELD_LABELS)
def test_a_label_number_is_flagged_on_a_bounded_role(value):
    rules = datasheet_checks.load_rules()
    fact = {
        **_fact(value, ""),
        "field_name": "specific heat ratio",
        "field_label": "Specific heat ratio",
        "page": 1,
    }
    doubt = datasheet_checks.implausible(fact, "specific_heat_ratio", rules)
    assert doubt is not None and "cannot be read as a number" in doubt


@pytest.mark.parametrize("value", ["5", "max 5", "Fire", "-5"])
def test_a_number_or_a_word_is_no_label_number(value):
    assert not numparse.has_label_number(value)


# ------------------------------------------------------------- a dash apart from digits

#: Something before a dash kept apart from its digits: a label, a number, nothing, a comparator.
DASH_LEADS = ["", "A", "Ab ", "Ab 2 ", "Ab2", "max ", "T = ", "(", "5 "]
#: A dash kept apart from its digits by space, a bracket or a colon; or a Unicode minus or an en dash
#: kept apart.
APART = [
    "- ",
    " - ",
    "-(",
    "-:",
    "-[",
    "- (",
    f"{U_MINUS} ",
    f"{EN_DASH} ",
    f" {EN_DASH} ",
    "-  ",
]
ENDINGS = [
    " C or lower",
    " C or less",
    " mm or more",
    " mm or larger",
    " bar or greater",
]
LEADS = ["", "The design value shall be ", "Rated at "]
APART_SENTENCES = [
    lead + d + a + n + e
    for lead, d, a, n, e in itertools.product(
        LEADS, DASH_LEADS, APART, ["5", "29", "1,5"], ENDINGS
    )
]


@pytest.mark.parametrize("text", APART_SENTENCES)
def test_a_dash_apart_from_its_digits_gives_no_limit(text):
    assert requirements_3b.parse_limit(text) is None
    assert requirements_3b.parse_limit_or_range(text) is None


@pytest.mark.parametrize("value", ["-50", "0", "10", "40", "200"])
@pytest.mark.parametrize("text", APART_SENTENCES[::7])
def test_a_dash_apart_goes_to_review(text, value):
    unit = "mm" if " mm " in text else "bar" if " bar " in text else "C"
    assert comparison.compare(_requirement(text), _fact(value, unit))["status"] == (
        comparison.NEEDS_ENGINEER_REVIEW
    )


#: After a comparator, a sign `_LIMIT` cannot read: it skipped this comparator and read a later one.
UNREAD_SIGNS = [U_MINUS, EN_DASH, "- ", "-(", "(-", "(", f"{U_MINUS} ", "\u2010", "( -"]
FRONT = [
    "The temperature shall not exceed {} C, minimum 5 C",
    "The temperature shall not exceed {} C or 40 C",
    "maximum {} C, minimum -40 C",
    "The temperature shall not be lower than {} C and shall not exceed 40 C",
]
FRONT_SENTENCES = [
    f.format(s + n) for f, s, n in itertools.product(FRONT, UNREAD_SIGNS, ["5", "29"])
]


@pytest.mark.parametrize("text", FRONT_SENTENCES)
def test_an_unread_sign_after_a_comparator_gives_no_limit(text):
    assert requirements_3b.parse_limit(text) is None
    assert requirements_3b.parse_limit_or_range(text) is None


@pytest.mark.parametrize("value", ["-50", "-29", "0", "10", "39", "100"])
@pytest.mark.parametrize("text", FRONT_SENTENCES)
def test_an_unread_sign_after_a_comparator_goes_to_review(text, value):
    assert comparison.compare(_requirement(text), _fact(value))["status"] == (
        comparison.NEEDS_ENGINEER_REVIEW
    )


CLAUSES = [
    "The temperature shall not exceed 40 C, except pumps which shall be {} C or lower",
    "The temperature shall not exceed 40 C, except for pumps, which shall be {} C or lower",
    "The temperature shall be 40 C or lower, except pumps which shall be {} C or lower",
    "The temperature shall not exceed 40 C unless the pump is {} C or lower",
    "Where the pump is {} C or lower, the temperature shall not exceed 40 C",
    "The temperature shall be between 10 C and 40 C, except pumps at {} C or lower",
    "{} C or lower, 40 C or lower",
    "5 C or lower, {} C or lower",
]
EXCEPTION_GRID = [
    c.format(d + a + n)
    for c, d, a, n in itertools.product(
        CLAUSES, ["Ab 2 ", "A", ""], ["- ", "-(", f"{U_MINUS} "], ["15", "29"]
    )
]


@pytest.mark.parametrize("subject", ["pumps", None])
@pytest.mark.parametrize("value", ["-40", "10", "39", "100"])
@pytest.mark.parametrize("text", EXCEPTION_GRID)
def test_an_unreadable_exception_or_second_limit_sends_the_requirement_to_review(
    text, value, subject
):
    status = comparison.compare(_requirement(text), _fact(value), subject=subject)[
        "status"
    ]
    assert status == comparison.NEEDS_ENGINEER_REVIEW


@pytest.mark.parametrize(
    "text, raw",
    [
        ("-5 C or lower", "-5"),
        ("(-15 C or lower", "-15"),
        ("T = -29 C or lower", "-29"),
        ("T: -29 C or lower", "-29"),
        ("-20 - -10 C or lower", "-10"),
        ("3 -5 C or lower", "-5"),
        ("5 C or lower", "5"),
        ("5 C or lower, 40 C or lower", "5"),
        ("The temperature shall not exceed -29 C", "-29"),
        ("The temperature shall not exceed 40 C", "40"),
        ("maximum -29 C, minimum -40 C", "-29"),
    ],
)
def test_real_limits_keep_their_value_and_sign(text, raw):
    assert requirements_3b.parse_limit(text)["raw_value"] == raw


# ---------------------------------------------------- a minus folded into a hyphen (#1640)

LETTER_DASHES = ["-", "\u2010", EN_DASH]


@pytest.mark.parametrize("dash", LETTER_DASHES)
@pytest.mark.parametrize("label", ["A", "Abcd", "AB"])
@pytest.mark.parametrize("number", ["29", "5.5"])
def test_a_number_joined_to_a_letter_is_no_stated_figure(label, dash, number):
    source = f"{label}{dash}{number} C"
    for value in (number, f"-{number}"):
        assert not numparse.value_in_text(value, source)
        assert not numparse.value_in_text(f"{value} C", source)
    assert numparse.number_keys(source) == set()
    assert not rule_eval.verify_numbers({"rows": [{"from": float(number)}]}, source)


def test_a_spaced_or_bound_negative_is_still_stated():
    for source in ("Ab -29 C", "Ab: -29 C", "Ab = -29 C", "-29 C", f"Ab {U_MINUS}29 C"):
        assert numparse.value_in_text("-29", source)
        assert not numparse.value_in_text("29", source)


def test_an_unfolded_unicode_minus_after_a_letter_stays_a_minus():
    # #1635's decision: an unfolded source keeps the sign the page printed.
    assert numparse.number_keys(f"Ab{U_MINUS}29 C") == {-29.0}


# ---------------------------------------------------------------- #1653: unit with number

UNITS = ["MPa", "bar", "mm", "kW", "C"]
OTHER = {"MPa": "bar", "bar": "MPa", "mm": "m", "kW": "hp", "C": "F"}


def _quotes(value: str, unit: str):
    """(quote, the unit sits with the value) for generated quotes."""
    other = OTHER[unit]
    yield f"{value} {other} and 5 {unit}", False
    yield f"{value} {other}, 5 {unit}", False
    yield f"5 {unit} and {value} {other}", False
    yield f"{value} {other} (7 {unit})", False
    yield f"{unit}: {value} {other}", False
    yield f"{value} {unit} and 5 {other}", True
    yield f"5 {other} and {value} {unit}", True
    yield f"{value}{unit}", True
    yield f"{value} to 12 {unit}", True
    yield f"{value}-12 {unit}", True
    yield f"{value} / 12 {unit}", True
    yield f"{value} ({unit})", True
    yield f"Ab, {unit}: {value}", True


UNIT_GRID = [
    (v, u, q, ok)
    for v in ("10", "-10", "2.5")
    for u in UNITS
    for q, ok in _quotes(v, u)
]


@pytest.mark.parametrize("value, unit, quote, ok", UNIT_GRID)
def test_a_unit_must_sit_with_its_number(value, unit, quote, ok):
    assert unit_tie.unit_with_value(value, unit, quote) is ok


def test_a_word_value_or_no_unit_is_left_to_the_other_checks():
    assert unit_tie.unit_with_value("Carbon steel", "mm", "5 mm Carbon steel")
    assert unit_tie.unit_with_value("10", None, "10 bar and 5 MPa")


PAGE = "Ab | Design pressure | 10 bar and 5 MPa\nAb | Set pressure | 8 MPa\n"


def test_claude_datasheet_refuses_a_unit_of_another_number():
    proposals, _ = claude_datasheet.parse_response(
        '{"facts": [{"field": "Design pressure", "value": "10", "unit": "MPa", '
        '"quote": "Design pressure | 10 bar and 5 MPa", "kind": "offered"}]}'
    )
    out = claude_datasheet.accept(proposals, PAGE, [])
    assert out["accepted"] == []
    assert out["counts"] == {claude_datasheet.Reason.VALUE_NOT_IN_QUOTE.value: 1}
    proposals, _ = claude_datasheet.parse_response(
        '{"facts": [{"field": "Set pressure", "value": "8", "unit": "MPa", '
        '"quote": "Set pressure | 8 MPa", "kind": "offered"}]}'
    )
    assert len(claude_datasheet.accept(proposals, PAGE, [])["accepted"]) == 1


def test_form_reader_refuses_a_unit_of_another_number():
    f = Field("design_pressure", "design pressure", None, ())
    rules = datasheet_checks.load_rules()
    wrong = {
        "value": "10",
        "unit": "MPa",
        "quote": "Design pressure | 10 bar and 5 MPa",
    }
    assert (
        form_reader.verify(f, wrong, PAGE, rules)
        == form_reader.Reason.UNIT_NOT_WITH_VALUE
    )
    right = {"value": "5", "unit": "MPa", "quote": "Design pressure | 10 bar and 5 MPa"}
    assert form_reader.verify(f, right, PAGE, rules) is None


def test_reader_api_refuses_a_unit_of_another_number():
    sentence = "The design pressure shall not exceed 10 bar and 5 MPa."
    proposal = {
        "kind": "limit",
        "operator": "<=",
        "value": "10",
        "unit": "MPa",
        "subject": "design pressure",
        "quote": sentence,
    }
    out = reader_api.accept([proposal], sentence)
    assert [r["reason"] for r in out["rejected"]] == [
        reader_api.Reason.VALUE_NOT_IN_QUOTE.value
    ]
    assert (
        len(reader_api.accept([{**proposal, "unit": "bar"}], sentence)["accepted"]) == 1
    )


def test_compiled_rule_proof_already_ties_a_number_to_its_unit():
    body = "the design pressure shall not exceed 10 bar and 5 mpa"
    problem = compiled_rule_proof._limit_problem(
        "10", "MPa", "<=", body, body, "design pressure"
    )
    assert problem == "number_and_unit_apart"


def test_datasheet_ai_does_not_prove_a_unit_of_another_number():
    rule = {
        "id": "u1",
        "page": 1,
        "field_name": "design pressure",
        "field_label": "Design pressure",
        "field_value": "10",
        "raw_value": "10",
        "raw_unit": None,
        "is_blank": 0,
        "value_column": None,
        "normalized_value": None,
        "normalized_unit": None,
    }
    ai = {
        "page": 1,
        "field_name": "design pressure",
        "field": "design pressure",
        "value": "10",
        "unit": "MPa",
        "kind": "offered",
        "quote": "Design pressure 10 bar and 5 MPa",
    }
    assert datasheet_ai.reading_relation(rule, ai) == datasheet_ai.SAME
    assert datasheet_ai.reading_relation(
        rule, {**ai, "quote": "Design pressure 10 MPa"}
    ) == (datasheet_ai.AI_UNIT)


def test_the_standards_gates_already_tie_a_number_to_its_unit():
    sentence = "The design pressure shall not exceed 10 bar and 5 MPa."
    check, why = ai_requirements.verify_proposal(
        {
            "has_limit": True,
            "field": "design pressure",
            "value": "10",
            "unit": "MPa",
            "operator": "<=",
            "quote": "shall not exceed 10 bar and 5 MPa",
        },
        sentence,
    )
    assert check is None and why == ai_requirements.MODEL_VALUE_DISAGREED
    assert (
        standards_converter.limit_scope(
            sentence.lower(), "shall not exceed 10 bar and 5 MPa", "10", "MPa"
        )
        is None
    )
