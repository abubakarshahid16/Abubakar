"""#899 (PF2): a clause is excused as "not applicable" only on CONTRARY
evidence - a stated value that names something else of the same kind.

PF1's first run (#881): "For a conventional valve, the built-up back pressure
shall not exceed 10 % of the set pressure" was excused on an invented sheet
that states "Valve type: Conventional" and 14 %. The reason given: "2 field(s)
state a value and none of them is 'valve'". A value that does not repeat the
condition's word says nothing about the condition.

UNKNOWN is not NOT APPLICABLE: the first leaves the clause possibly governing
and asks an engineer; the second hides it. Invented data only.
"""

from __future__ import annotations

import pytest

from app import comparison, conditions


def _req(
    condition,
    text="The built-up back pressure shall not exceed 10 % of the set pressure.",
):
    return {
        "id": "r1",
        "requirement_type": "numeric_limit",
        "condition": condition,
        "operator": "<=",
        "raw_value": "10",
        "raw_unit": "%",
        "value": 10.0,
        "unit": "%",
        "subject": "built-up back pressure",
        "requirement_text": text,
        "source_text": text,
        "standard_document_id": "doc_std",
    }


def _fact(name, value, **more):
    return {
        "id": f"f-{name}",
        "field_name": name,
        "field_label": name,
        "field_value": value,
        "page": 1,
        "extraction_method": "extracted",
        "is_blank": 0,
        "document_id": "doc_sheet",
        **more,
    }


def _gate(condition, facts):
    return conditions.evaluate(_req(condition), facts)


def test_a_field_that_does_not_repeat_the_conditions_word_does_not_excuse_the_clause():
    """THE CASE of PF1's PSV sheet. A field with another name ("relief case type") says nothing about
    the condition; one NAMED for the equipment ("valve type") that says the qualifier establishes it
    (#899, `condition_stated`), which is the opposite of excusing the clause."""
    gate = _gate(
        "a conventional valve",
        [_fact("relief case type", "Conventional"), _fact("seat", "Soft")],
    )
    assert gate["state"] == conditions.UNKNOWN
    assert "none names another" in gate["reason"] and gate["evidence"] is None
    gate = _gate(
        "a conventional valve",
        [
            _fact("valve type", "Conventional"),
            _fact("relief case type", "Blocked outlet"),
        ],
    )
    assert (
        gate["state"] == conditions.SATISFIED
        and gate["state"] != conditions.NOT_SATISFIED
    )


def test_the_planted_defect_is_checked_and_found_never_excused():
    facts = [
        _fact("valve type", "Conventional"),
        _fact("built up back pressure", "14 %", raw_value="14", raw_unit="%"),
    ]
    verdict = comparison._compare(
        _req("a conventional valve"), facts[1], submittal_facts=facts
    )
    assert verdict["status"] == comparison.NON_COMPLIANT
    assert verdict["status"] != comparison.NOT_APPLICABLE


@pytest.mark.parametrize(
    "shape, condition, field, value, other",
    [
        (
            conditions.SHAPE_CLASS,
            "a conventional valve",
            "equipment type",
            "Centrifugal pump",
            "pump",
        ),
        (
            conditions.SHAPE_MATERIAL,
            "carbon steel systems",
            "shell material",
            "Stainless steel 316L",
            "stainless",
        ),
        (
            conditions.SHAPE_SERVICE,
            "pumps in hydrocarbon service",
            "service",
            "Potable water",
            "potable water",
        ),
    ],
)
def test_a_value_that_names_something_else_of_the_same_kind_excuses_it_and_says_what(
    shape, condition, field, value, other
):
    gate = conditions._evaluate_terms(shape, condition, [_fact(field, value)])
    assert gate["state"] == conditions.NOT_SATISFIED
    assert gate["evidence"]["field_name"] == field and other in gate["reason"]


def test_the_term_route_names_the_other_thing_it_found():
    gate = conditions._evaluate_terms(
        conditions.SHAPE_CLASS,
        "a conventional valve",
        [_fact("equipment type", "Centrifugal pump")],
    )
    assert gate["state"] == conditions.NOT_SATISFIED
    assert "'equipment type' states 'pump', which is not 'valve'" in gate["reason"]
    assert gate["evidence"]["field_value"] == "Centrifugal pump"


def test_a_value_that_says_the_word_still_establishes_the_condition():
    gate = conditions._evaluate_terms(
        conditions.SHAPE_CLASS,
        "a conventional valve",
        [_fact("equipment type", "Pressure relief valve")],
    )
    assert gate["state"] == conditions.SATISFIED


def test_a_narrower_or_wider_word_for_the_same_thing_is_not_another_thing():
    """The condition says "relief valve"; a value saying "valve" is the same
    family, not contrary evidence (and "vessel" inside "pressure vessel")."""
    gate = conditions._evaluate_terms(
        conditions.SHAPE_CLASS,
        "pressure vessel internals",
        [_fact("equipment type", "Vessel, horizontal")],
    )
    assert gate["state"] != conditions.NOT_SATISFIED


@pytest.mark.parametrize(
    "value", ["Conventional", "Yes", "Type 2", "See note 4", "Horizontal, split case"]
)
def test_values_that_name_no_kind_at_all_never_excuse(value):
    gate = conditions._evaluate_terms(
        conditions.SHAPE_CLASS, "a conventional valve", [_fact("valve type", value)]
    )
    assert gate["state"] == conditions.UNKNOWN
