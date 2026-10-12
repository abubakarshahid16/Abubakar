"""#858: a conditional limit nobody checked, and a pressure of the opposite
sign, are never a plain Meets.

Found by the gold-lite key on a real vessel sheet (s2, 12 Oct 2026). Two
verdicts were reported as Meets and the planner ruled them false results
until shown otherwise:

  1. "In <an environment>, the operating temperature shall not exceed A for
     <one material>, and B for <another>" was compared with A. The
     extraction had left the requirement's `condition` column empty, so the
     condition gate (which reads only that column) had nothing to check.
  2. A negative gauge pressure was compared with a positive limit and passed
     by its sign, whatever its size.

Now: a numeric limit whose own sentence opens with a conditional clause, or
states several limits each for a different case, goes to the engineer with
the unchecked condition named; and two pressures of opposite sign are not
compared. Every test goes through `comparison.compare`, the function a
review calls. Invented requirements and values only.
"""
from __future__ import annotations

import pytest

from app import comparison, conditions


def _requirement(text, **fields):
    base = {"id": "r", "standard_document_id": None, "requirement_type": "numeric_limit",
            "requirement_text": text, "source_text": text, "operator": "<=", "raw_value": "80",
            "raw_unit": "°C", "field": "operating temperature", "exceptions": [], "condition": None}
    return {**base, **fields}


def _fact(value="30", unit="°C", name="operating temperature"):
    return {"id": "f", "document_id": None, "field_name": name, "field_label": name.capitalize(),
            "field_value": f"{value} {unit}", "raw_value": value, "raw_unit": unit, "is_blank": 0,
            "blank_marker": None}


PLAIN = "The operating temperature shall not exceed 80 °C."
CONDITIONAL = ("In acid gas environments, the operating temperature shall not exceed 80 °C for grade A, "
               "and 100 °C for grade B.")


def test_a_plain_limit_still_gives_meets_and_does_not_meet():
    assert comparison.compare(_requirement(PLAIN), _fact("30"))["status"] == comparison.COMPLIANT
    assert comparison.compare(_requirement(PLAIN), _fact("95"))["status"] == comparison.NON_COMPLIANT


def test_the_real_shape_is_an_engineer_question_naming_the_condition():
    """30 °C against "not more than 80 °C" would be Meets - if the sentence
    were not about one environment and two materials nobody established."""
    verdict = comparison.compare(_requirement(CONDITIONAL), _fact("30"))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "In acid gas environments" in verdict["rationale"]
    assert "did not" in verdict["rationale"] and "no comparison was made" in verdict["rationale"]
    assert verdict["condition"]["state"] == conditions.UNKNOWN
    assert verdict["limit"] is None                       # no limit is shown as if it had been applied


def test_it_is_never_a_does_not_meet_either():
    """The other half of the same guess: 95 °C "fails" 80 °C only if the
    condition holds."""
    assert comparison.compare(_requirement(CONDITIONAL), _fact("95"))["status"] == comparison.NEEDS_ENGINEER_REVIEW


@pytest.mark.parametrize("text", [
    "Where the fluid is corrosive, the operating temperature shall not exceed 80 °C.",
    "When the vessel is insulated, the operating temperature shall not exceed 80 °C.",
    "If cladding is specified, the operating temperature shall not exceed 80 °C.",
    "Unless otherwise approved, the operating temperature shall not exceed 80 °C.",
    "Under cyclic service, the operating temperature shall not exceed 80 °C.",
    "(b) Where the fluid is corrosive, the operating temperature shall not exceed 80 °C.",
    "The operating temperature shall not exceed 80 °C for grade A, and 100 °C for grade B.",
])
def test_a_sentence_that_states_its_own_condition_is_not_decided(text):
    assert conditions.unread_condition(_requirement(text))
    assert comparison.compare(_requirement(text), _fact("30"))["status"] == comparison.NEEDS_ENGINEER_REVIEW


@pytest.mark.parametrize("text", [
    PLAIN,
    "In addition, the operating temperature shall not exceed 80 °C.",
    "In general, the operating temperature shall not exceed 80 °C.",
    "In accordance with the design code, the operating temperature shall not exceed 80 °C.",
    "In no case shall the operating temperature exceed 80 °C.",
    "The operating temperature shall not exceed 80 °C for the shell.",        # one limit, one subject
    "The operating temperature, in normal operation, shall not exceed 80 °C.",  # not an opening clause
])
def test_an_opener_that_only_orders_the_text_is_not_a_condition(text):
    assert conditions.unread_condition(_requirement(text)) is None
    assert comparison.compare(_requirement(text), _fact("30"))["status"] == comparison.COMPLIANT


def test_an_extracted_condition_is_still_the_gates_business():
    """A requirement whose `condition` column is filled goes through
    `conditions.evaluate` exactly as before; the new reading does not touch it."""
    with_column = _requirement(CONDITIONAL, condition="acid gas environments")
    assert conditions.unread_condition(with_column) is None
    verdict = comparison.compare(with_column, _fact("30"), submittal_facts=[_fact("30")])
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert verdict["condition"]["shape"] != "unread"


def test_only_numeric_limits_are_read_this_way():
    statement = _requirement(CONDITIONAL, requirement_type="statement")
    assert conditions.unread_condition(statement) is None


# ------------------------------------------------------------ opposite signs

def _pressure(limit="1", unit="barg", text="The external design pressure shall not exceed 1 barg."):
    return _requirement(text, raw_value=limit, raw_unit=unit, field="external design pressure")


def test_a_negative_pressure_does_not_pass_a_positive_limit_by_its_sign():
    """-0.5 <= 1 is true of the numbers and says nothing about the pressure:
    the same sentence would 'pass' -50."""
    for value in ("-0.5", "-50"):
        verdict = comparison.compare(_pressure(), _fact(value, "barg", "external design pressure"))
        assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW, value
        assert "opposite signs" in verdict["rationale"] and "magnitudes" in verdict["rationale"]


def test_the_other_way_round_is_not_decided_either():
    verdict = comparison.compare(_pressure(limit="-1", text="The design vacuum shall not exceed -1 barg."),
                                 _fact("0.5", "barg", "external design pressure"))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW and "opposite signs" in verdict["rationale"]


def test_pressures_of_the_same_sign_are_compared_as_before():
    within = comparison.compare(_pressure(), _fact("0.5", "barg", "external design pressure"))
    over = comparison.compare(_pressure(), _fact("3", "barg", "external design pressure"))
    assert within["status"] == comparison.COMPLIANT and over["status"] == comparison.NON_COMPLIANT
    both_negative = comparison.compare(_pressure(limit="-0.2", text="The design vacuum shall not exceed -0.2 barg."),
                                       _fact("-0.5", "barg", "external design pressure"))
    assert "opposite signs" not in both_negative["rationale"]


def test_a_negative_temperature_is_a_real_value_and_is_still_compared():
    assert comparison.compare(_requirement(PLAIN), _fact("-20"))["status"] == comparison.COMPLIANT
