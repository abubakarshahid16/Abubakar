"""A comparator that FOLLOWS the number ("3 m or less", "5 mm or more", "50 mm
or above") states a limit, and the limit reader (`_LIMIT`) only read a
comparator in front of it, so the clause had none and a sheet value got no
verdict. The direction is the shared vocabulary's (`comparators`). Invented
sentences only."""
from __future__ import annotations

import pytest

from app import comparison, requirements_3b as r


@pytest.mark.parametrize("sentence, operator, raw, unit", [
    ("The cable shall be 3 m or less.", "<=", "3", "m"),
    ("The level shall be 5 mm or fewer.", "<=", "5", "mm"),
    ("The level shall be 5 mm or lower.", "<=", "5", "mm"),
    ("The level shall be 5 mm or more.", ">=", "5", "mm"),
    ("The pressure shall be 10 bar or greater.", ">=", "10", "bar"),
    ("Cover shall be 50 mm or above.", ">=", "50", "mm"),
    ("The temperature shall be 60 degC or below.", "<=", "60", "degC"),
])
def test_a_trailing_comparator_states_a_limit(sentence, operator, raw, unit):
    limit = r.parse_limit(sentence)
    assert limit is not None and (limit["operator"], limit["raw_value"], limit["raw_unit"]) == (operator, raw, unit)
    assert r.classify(sentence, limit) == "numeric_limit"
    assert not r.contradicts_source(limit, sentence)


@pytest.mark.parametrize("sentence", [
    "The cable shall be 3 m or so.",                      # no direction
    "The cable shall be 3 m or 4 m.",                     # alternatives, not a limit
    "The cable shall be 3 widgets or less.",              # not a unit
    "Use items 3 or more of the list.",                   # no unit
])
def test_when_unsure_a_sentence_states_no_trailing_limit(sentence):
    assert r.parse_limit(sentence) is None


def test_a_leading_comparator_is_still_read_first():
    limit = r.parse_limit("The wall shall be not less than 5 mm.")
    assert (limit["operator"], limit["raw_value"]) == (">=", "5")


def _req(operator):
    return {"id": "r1", "standard_document_id": "doc_std", "requirement_type": "numeric_limit", "operator": operator,
            "raw_value": "5", "raw_unit": "mm", "value": 5000.0, "unit": "um", "subject": "level", "clause": "4.1",
            "requirement_text": "x", "source_text": "x"}


def _fact(value):
    return {"id": "f1", "document_id": "doc_sheet", "submittal_document_id": "doc_sheet", "field_name": "level",
            "field_value": f"{value} mm", "raw_value": str(value), "raw_unit": "mm", "is_blank": 0, "page": 1,
            "extraction_method": "extracted", "equipment_tag": None}


def test_the_stored_limit_is_compared_in_the_right_direction():
    ceiling = comparison._compare(_req(r.parse_limit("The level shall be 5 mm or less.")["operator"]), _fact(7),
                                  submittal_facts=[_fact(7)])
    assert ceiling["status"] == comparison.NON_COMPLIANT
    floor = comparison._compare(_req(r.parse_limit("The level shall be 5 mm or more.")["operator"]), _fact(7),
                                submittal_facts=[_fact(7)])
    assert floor["status"] == comparison.COMPLIANT
