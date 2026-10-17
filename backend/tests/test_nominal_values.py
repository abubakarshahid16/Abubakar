"""A clause that states ONE value ("shall operate from a 24 V DC loop supply")
is stored with that value and its stated precision and compared by code:
equal within the precision -> COMPLIANT; ANY other value -> an engineer's
question with both values shown, NEVER NON_COMPLIANT (planner, 14 Oct 2026).
Invented data only."""
from __future__ import annotations

import pytest

from app import comparison, requirements_3b as r


def _parse(sentence):
    return r.parse_limit_or_range(sentence)


@pytest.mark.parametrize("sentence, raw, unit, low, high", [
    ("The transmitter shall operate from a 24 V DC loop supply.", "24", "V", 23.5, 24.5),
    ("The supply voltage shall be 24 V DC.", "24", "V", 23.5, 24.5),
    ("The cable shall be 3 m.", "3", "m", 2.5, 3.5),
    ("The velocity shall be 2.5 m/s.", "2.5", "m/s", 2.45, 2.55),
    ("The loop shall be powered from a 24.0 V DC supply.", "24.0", "V", 23.95, 24.05),
])
def test_a_clause_that_states_one_value(sentence, raw, unit, low, high):
    limit = _parse(sentence)
    assert limit is not None and limit["operator"] == r.NOMINAL_OPERATOR
    assert (limit["raw_value"], limit["raw_unit"]) == (raw, unit)
    assert (limit["value_low"], limit["value_high"]) == pytest.approx((low, high))
    assert r.classify(sentence, limit) == r.NOMINAL_VALUE


@pytest.mark.parametrize("sentence", [
    "The cable shall be 3 m or less.",                                    # a limit
    "The cable shall be at least 3 m.",
    "The cable shall be between 3 m and 5 m.",                            # a range
    "The cable shall not be 3 m.",                                        # a negation
    "The cable shall be 3 widgets long.",                                  # not a unit
    "The supply shall be 24 V DC at 50 Hz.",                              # a second quantity
    "The pump shall be installed 3 m above grade.",                       # not a stating verb
    "See clause 4.2.1 for the 24 V supply.",
])
def test_when_unsure_a_sentence_is_not_a_nominal_value(sentence):
    limit = _parse(sentence)
    assert limit is None or limit["operator"] != r.NOMINAL_OPERATOR


def test_a_nominal_value_that_hands_the_number_to_a_table_is_the_tables_row():
    sentence = "The supply shall be 24 V DC as given in Table 4."
    assert r.classify(sentence, _parse(sentence)) == r.TABLE_ROW


def test_it_is_a_stored_matchable_type_the_api_can_return():
    assert r.NOMINAL_VALUE in r.STORED_REQUIREMENT_TYPES and r.NOMINAL_VALUE in comparison.MATCHABLE_TYPES


# ---------------------------------------------------------------- comparing
def _req(**more):
    return {"id": "r1", "standard_document_id": "doc_std", "requirement_type": "nominal_value", "operator": "nominal",
            "raw_value": "24", "raw_unit": "V", "value": 24.0, "unit": "V", "value_low": 23.5, "value_high": 24.5,
            "subject": "loop supply", "clause": "5.2", "requirement_text": "x", "source_text": "x", **more}


def _fact(value, unit="V", **more):
    return {"id": "f1", "document_id": "doc_sheet", "submittal_document_id": "doc_sheet", "field_name": "loop supply",
            "field_value": f"{value} {unit}".strip(), "raw_value": str(value), "raw_unit": unit, "is_blank": 0,
            "page": 1, "extraction_method": "extracted", "equipment_tag": None, **more}


def _judge(req, fact):
    return comparison._compare(req, fact, submittal_facts=[fact])


@pytest.mark.parametrize("value", [24, 24.4, 23.6])
def test_the_stated_value_within_its_precision_meets(value):
    verdict = _judge(_req(), _fact(value))
    assert verdict["status"] == comparison.COMPLIANT and verdict["limit"] == "24 V"


@pytest.mark.parametrize("value", [12, 25, 48, 0])
def test_any_other_value_is_an_engineers_question_and_never_a_breach(value):
    """THE RULE: a nominal value is not a limit."""
    verdict = _judge(_req(), _fact(value))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert verdict["status"] != comparison.NON_COMPLIANT
    assert verdict["rationale"].startswith(comparison.NOMINAL_VALUE_REASON)
    assert "24 V" in verdict["rationale"] and str(value) in verdict["rationale"]


def test_another_unit_of_the_same_quantity_is_converted():
    verdict = _judge(_req(raw_value="1", raw_unit="bar", value=1.0, unit="bar", value_low=0.5, value_high=1.5),
                     _fact(100, "kPa"))
    assert verdict["status"] == comparison.COMPLIANT


def test_a_unit_that_cannot_be_compared_and_a_blank_are_never_a_verdict():
    assert _judge(_req(), _fact(24, "mm"))["status"] == comparison.NEEDS_ENGINEER_REVIEW
    blank = _fact("", is_blank=1, raw_value=None, blank_marker="TBD")
    assert _judge(_req(), blank)["status"] == comparison.MISSING_INFORMATION


def test_a_requirement_with_no_stored_precision_is_never_a_verdict():
    verdict = _judge(_req(value_low=None, value_high=None), _fact(24))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
