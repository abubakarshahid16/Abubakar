"""#895 (PF2): a sentence that states a TWO-SIDED limit is stored with both
ends and compared as two ordinary limits.

PF1's first run (#881): "At normal flow the valve shall operate between 20 %
and 80 % of its travel" against a sheet saying 88 % got no verdict - the
sentence was a `statement` (or, when another phrase in it parsed, a ONE-SIDED
limit). On a copy of the library 130 stored sentences are worded as a range.

A range is two limits, so every guard of the comparison - units, pressure
signs and references, a range on the sheet's side, the condition gate -
applies to it exactly as to a one-sided limit. Invented data only.
"""
from __future__ import annotations

import pytest

from app import comparison, db, requirements_3b as r, standards
from tests.test_w6_640_requirements_supersede import _standard, temp_storage  # noqa: F401


def _parse(sentence):
    return r.parse_limit_or_range(sentence)


# ------------------------------------------------------------------ reading
@pytest.mark.parametrize("sentence, low, high, unit", [
    ("At normal flow the valve shall operate between 20 % and 80 % of its travel.", 20.0, 80.0, "%"),
    ("The rated flow shall lie between 80 % and 110 % of the best efficiency flow.", 80.0, 110.0, "%"),
    ("The velocity shall be between 1.0 m/s and 2.5 m/s.", 1.0, 2.5, "m/s"),
    ("The pressure shall be between 5 and 10 bar.", 5.0, 10.0, "bar"),
    ("The pressure shall be from 5 to 10 bar.", 5.0, 10.0, "bar"),
    ("The setting shall be in the range of 10 to 40 mm.", 10.0, 40.0, "mm"),
    ("The setting shall be within the range of 10 to 40 mm.", 10.0, 40.0, "mm"),
    ("The offset shall be between -5 mm and 5 mm.", -5.0, 5.0, "mm"),
    ("The stock shall be between 1,000 kg and 2,500 kg.", 1000.0, 2500.0, "kg"),
])
def test_a_sentence_that_states_a_range(sentence, low, high, unit):
    limit = _parse(sentence)
    assert limit["operator"] == r.RANGE_OPERATOR
    assert (limit["value_low"], limit["value_high"], limit["raw_unit"]) == (low, high, unit)
    assert r.classify(sentence, limit) == r.RANGE_LIMIT
    assert limit["value"] is None and "_ends" not in limit


@pytest.mark.parametrize("sentence", [
    "The value shall not be between 5 and 10 mm.",                          # a negation: not a range to stay inside
    "Never be between 5 and 10 mm.",
    "See items from 5 to 10.",                                              # no unit: item numbers
    "The supports shall be between 5 mm and 2 in apart.",                   # two different units
    "The span shall be between 10 and 5 mm.",                               # low above high
    "The supports shall be between the pump and the wall.",                 # no numbers
    "The wall shall be at least 5 mm between supports and walls.",          # a one-sided limit
])
def test_when_unsure_a_sentence_is_not_a_range(sentence):
    limit = _parse(sentence)
    assert not limit or limit["operator"] != r.RANGE_OPERATOR


def test_a_range_and_another_number_is_left_for_an_engineer():
    sentence = "Spacing shall be between 20 % and 80 % of travel, and not above 5 bar."
    limit = _parse(sentence)
    assert limit["operator"] == "<=" and limit["raw_value"] == "5"          # the limit it was, not a range


def test_a_range_that_defers_to_a_table_stays_a_table_row():
    sentence = "The pressure shall be between 5 and 10 bar as given in Table 4."
    assert r.classify(sentence, _parse(sentence)) == r.TABLE_ROW


def test_a_range_is_a_stored_type_the_api_can_return():
    assert r.RANGE_LIMIT in r.STORED_REQUIREMENT_TYPES and r.TABLE_RANGE in r.STORED_REQUIREMENT_TYPES
    assert r.RANGE_LIMIT in comparison.MATCHABLE_TYPES


def test_a_standard_stores_the_range_with_both_ends():
    std = _standard(lines=[
        "5.3 Travel",
        "At normal flow the valve shall operate between 20 % and 80 % of its travel",
        "under rated operating conditions at the supplier test bench.",
    ])
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    row = db.connect().execute(
        "SELECT * FROM standard_requirements WHERE standard_document_id = ? AND superseded_at IS NULL", (std,)).fetchone()
    assert row["requirement_type"] == "range_limit" and row["operator"] == "between"
    assert (row["value_low"], row["value_high"], row["raw_unit"]) == (20.0, 80.0, "%")
    assert row["raw_value"] == "20 to 80"


# ---------------------------------------------------------------- comparing
def _req(low=20.0, high=80.0, unit="%", **more):
    return {"id": "r1", "standard_document_id": "doc_std", "requirement_type": "range_limit", "operator": "between",
            "raw_value": f"{low:g} to {high:g}", "raw_unit": unit, "value_low": low, "value_high": high,
            "subject": "travel at normal flow", "clause": "4.1", "requirement_text": "x", "source_text": "x", **more}


def _fact(value, unit="%", **more):
    return {"id": "f1", "document_id": "doc_sheet", "submittal_document_id": "doc_sheet", "field_name": "travel",
            "field_value": f"{value} {unit}".strip(), "raw_value": str(value), "raw_unit": unit, "is_blank": 0,
            "page": 1, "extraction_method": "extracted", "equipment_tag": None, **more}


def _judge(req, fact, facts=None):
    return comparison._compare(req, fact, submittal_facts=facts if facts is not None else [fact])


@pytest.mark.parametrize("value", [20, 50, 80])
def test_a_value_inside_the_range_meets_ends_included(value):
    verdict = _judge(_req(), _fact(value))
    assert verdict["status"] == comparison.COMPLIANT
    assert "within the required range between 20 and 80 %" in verdict["rationale"]
    assert verdict["limit"] == "between 20 and 80 %"


def test_a_value_above_the_high_end_does_not_meet_and_the_rationale_names_the_end():
    """THE PLANTED DEFECT of PF1: 88 % against 20 to 80 %."""
    verdict = _judge(_req(), _fact(88))
    assert verdict["status"] == comparison.NON_COMPLIANT
    assert verdict["rationale"].startswith(comparison.RANGE_LIMIT_REASON) and "above the highest value" in verdict["rationale"]
    assert verdict["limit"] == "between 20 and 80 %"


def test_a_value_below_the_low_end_does_not_meet():
    verdict = _judge(_req(), _fact(12))
    assert verdict["status"] == comparison.NON_COMPLIANT and "below the lowest value" in verdict["rationale"]


def test_a_range_on_the_sheet_must_lie_inside_the_required_range():
    inside = _judge(_req(), _fact(30, field_value="30 to 70 %", raw_value="30 to 70"))
    assert inside["status"] in (comparison.COMPLIANT, comparison.NEEDS_ENGINEER_REVIEW)
    assert inside["status"] != comparison.NON_COMPLIANT
    spills = _judge(_req(), _fact(30, field_value="30 to 90 %", raw_value="30 to 90"))
    assert spills["status"] != comparison.COMPLIANT


def test_another_unit_of_the_same_quantity_is_converted():
    req = _req(5.0, 10.0, "bar")
    assert _judge(req, _fact(100, "psi"))["status"] == comparison.COMPLIANT          # 6.9 bar
    assert _judge(req, _fact(200, "psi"))["status"] == comparison.NON_COMPLIANT      # 13.8 bar


def test_a_unit_that_cannot_be_compared_is_the_engineers_and_never_a_verdict():
    verdict = _judge(_req(5.0, 10.0, "bar"), _fact(7, "kg"))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_a_blank_value_is_the_contractors_to_provide_and_no_fact_is_missing():
    assert _judge(_req(), _fact("", "", is_blank=1, blank_marker="TBA", raw_value=None))["status"] == comparison.MISSING_INFORMATION
    assert comparison._compare(_req(), None)["status"] in (comparison.MISSING_INFORMATION, comparison.NOT_IN_DOCUMENT_SCOPE)


def test_a_range_with_ends_that_were_not_stored_is_never_a_verdict():
    verdict = _judge(_req(value_low=None), _fact(50))
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW and "ends were not stored" in verdict["rationale"]


def test_a_requirement_keeps_its_own_condition_gate():
    """The two ends go through `_compare`, so a condition the sheet does not
    establish holds the range back exactly as it holds a one-sided limit."""
    conditional = _req(condition="for steam service")
    verdict = _judge(conditional, _fact(88), [_fact(88)])
    assert verdict["status"] != comparison.NON_COMPLIANT
