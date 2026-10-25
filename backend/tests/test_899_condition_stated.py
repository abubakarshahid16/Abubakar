"""#899 (PF2): a condition the sheet STATES is checked; one it plainly rules out is excused.

PF1 planted a defect behind "For a conventional valve, the built-up back
pressure shall not exceed 10 %" on a sheet that says "Valve type: Conventional"
and 14 %: the review sent it to the engineer instead of checking it. The
mirror: "Where an internal lining is specified, its thickness shall be at least
3 mm" on a sheet that says "Internal lining: None" went to the engineer too.

Two general rules (`condition_stated`): a trusted field that NAMES the equipment
and SAYS the qualifier establishes the condition; a field named for the thing
alone that states "none" rules it out. Anything else stays UNKNOWN, a definite
answer from the older gate is never changed, and a value that is not trusted, a
placeholder or a conflict decides nothing. Invented data only.
"""

from __future__ import annotations

import pytest

from app import comparison, condition_stated, conditions


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


def _gate(condition, *facts):
    return conditions.evaluate(_req(condition), list(facts))


# ---------------------------------------------------------------- rule S: a stated qualifier
def test_a_field_that_names_the_equipment_and_says_the_qualifier_establishes_the_condition():
    gate = _gate("a conventional valve", _fact("Valve type", "Conventional"))
    assert gate["state"] == conditions.SATISFIED and gate["shape"] == "stated_qualifier"
    assert (
        gate["evidence"]["field_name"] == "Valve type"
        and gate["evidence"]["field_value"] == "Conventional"
    )


def test_the_planted_defect_is_now_checked_and_found():
    """PF1's D2: 14 % against 10 % is a breach, not an engineer's question."""
    facts = [
        _fact("valve type", "Conventional"),
        _fact("built up back pressure", "14 %", raw_value="14", raw_unit="%"),
    ]
    verdict = comparison._compare(
        _req("a conventional valve"), facts[1], submittal_facts=facts
    )
    assert verdict["status"] == comparison.NON_COMPLIANT
    assert verdict["condition"]["state"] == conditions.SATISFIED


def test_the_same_sheet_inside_the_limit_is_met_not_flagged():
    facts = [
        _fact("valve type", "Conventional"),
        _fact("built up back pressure", "8 %", raw_value="8", raw_unit="%"),
    ]
    verdict = comparison._compare(
        _req("a conventional valve"), facts[1], submittal_facts=facts
    )
    assert verdict["status"] == comparison.COMPLIANT


@pytest.mark.parametrize(
    "value",
    [
        "Balanced bellows",  # a different qualifier proves nothing here
        "Non-conventional",  # negation
        "Not conventional",  # negation
        "Balanced (not conventional)",  # negation inside a longer value
        "Pilot operated, other than conventional",
    ],
)
def test_a_different_or_negated_qualifier_leaves_the_condition_unknown_never_excused(
    value,
):
    gate = _gate("a conventional valve", _fact("Valve type", value))
    assert gate["state"] == conditions.UNKNOWN


def test_a_negated_condition_is_not_read():
    gate = _gate("a non-conventional valve", _fact("Valve type", "Conventional"))
    assert gate["state"] == conditions.UNKNOWN
    gate = _gate(
        "a valve that is not conventional", _fact("Valve type", "Conventional")
    )
    assert gate["state"] == conditions.UNKNOWN


def test_a_field_that_does_not_name_the_equipment_does_not_establish_it():
    gate = _gate("a conventional valve", _fact("Seat type", "Conventional"))
    assert gate["state"] == conditions.UNKNOWN


def test_every_qualifier_word_must_be_said():
    gate = _gate(
        "a conventional spring loaded valve", _fact("Valve type", "Conventional")
    )
    assert gate["state"] == conditions.UNKNOWN
    gate = _gate(
        "a conventional spring loaded valve",
        _fact("Valve type", "Conventional, spring loaded"),
    )
    assert gate["state"] == conditions.SATISFIED


# ---------------------------------------------------------------- rule P: presence
LINING = "an internal lining is specified"


def test_a_field_named_for_the_thing_that_says_none_rules_the_condition_out_and_says_what():
    gate = _gate(LINING, _fact("Internal lining", "None"))
    assert gate["state"] == conditions.NOT_SATISFIED and gate["shape"] == "presence"
    assert gate["evidence"]["field_value"] == "None" and "not there" in gate["reason"]


def test_the_clause_is_then_not_applicable_with_the_field_that_rules_it_out():
    text = (
        "Where an internal lining is specified, its thickness shall be at least 3 mm."
    )
    req = {
        **_req(LINING, text),
        "operator": ">=",
        "raw_value": "3",
        "raw_unit": "mm",
        "value": 3.0,
        "unit": "mm",
        "subject": "lining thickness",
    }
    facts = [
        _fact("Internal lining", "None"),
        _fact("lining thickness", "1 mm", raw_value="1", raw_unit="mm"),
    ]
    verdict = comparison._compare(req, facts[1], submittal_facts=facts)
    assert verdict["status"] == comparison.NOT_APPLICABLE
    assert verdict["rationale"].startswith(comparison.CONDITION_NOT_MET)
    assert verdict["condition"]["evidence"]["field_name"] == "Internal lining"


def test_a_field_named_for_the_thing_that_states_a_value_establishes_the_condition():
    assert _gate(LINING, _fact("Lining", "Rubber"))["state"] == conditions.SATISFIED
    assert (
        _gate(LINING, _fact("Internal lining required", "Yes"))["state"]
        == conditions.SATISFIED
    )


def test_a_field_about_another_aspect_of_the_thing_says_nothing_about_whether_it_is_there():
    assert (
        _gate(LINING, _fact("Lining holiday test", "None"))["state"]
        == conditions.UNKNOWN
    )
    assert (
        _gate(LINING, _fact("Lining thickness", "None"))["state"] == conditions.UNKNOWN
    )


@pytest.mark.parametrize("value", ["N/A", "TBD", "-", "by vendor", ""])
def test_a_placeholder_is_not_a_statement(value):
    assert _gate(LINING, _fact("Internal lining", value))["state"] == conditions.UNKNOWN


def test_no_field_for_the_thing_leaves_it_to_the_engineer():
    assert (
        _gate(LINING, _fact("Design pressure", "10 bar"))["state"] == conditions.UNKNOWN
    )
    assert conditions.evaluate(_req(LINING), [])["state"] == conditions.UNKNOWN


def test_two_fields_that_disagree_decide_nothing():
    gate = _gate(
        LINING, _fact("Internal lining", "None"), _fact("Lining required", "Yes")
    )
    assert gate["state"] == conditions.UNKNOWN


def test_a_value_that_is_not_trusted_is_not_evidence_and_its_presence_changes_nothing():
    shaky = _fact("Internal lining", "None", extraction_method="model")
    assert conditions._low_trust(shaky)
    assert _gate(LINING, shaky)["state"] == conditions.UNKNOWN
    # a trusted statement beside an untrusted one elsewhere on the sheet: the answer may not depend
    # on whether the untrusted value is counted
    other = _fact("Shell material", "Carbon steel", extraction_method="model")
    assert (
        _gate("a conventional valve", _fact("Valve type", "Conventional"), other)[
            "state"
        ]
        == conditions.UNKNOWN
    )


# ---------------------------------------------------------------- the older gate keeps its answers
def test_a_definite_answer_from_the_older_gate_is_never_changed():
    gate = _gate("a conventional valve", _fact("equipment type", "Centrifugal pump"))
    assert (
        gate["state"] == conditions.NOT_SATISFIED
        and "which is not 'valve'" in gate["reason"]
    )
    gate = _gate(
        "a conventional valve", _fact("equipment type", "Pressure relief valve")
    )
    assert (
        gate["state"] == conditions.SATISFIED
        and gate["shape"] == conditions.SHAPE_CLASS
    )


def test_a_requirement_with_no_condition_is_untouched():
    assert conditions.evaluate(_req(""), [_fact("Valve type", "Conventional")]) is None


def test_refine_returns_what_it_was_given_when_there_is_nothing_to_settle():
    kept = {
        "state": conditions.SATISFIED,
        "condition": "x",
        "reason": "",
        "evidence": None,
    }
    assert condition_stated.refine(kept, [_fact("Internal lining", "None")]) is kept
    assert condition_stated.refine(None, None) is None


# ---------------------------------------------------------------- cloud's review of #1272
@pytest.mark.parametrize(
    "value",
    ["Unlined", "None required", "None specified", "Absent", "No lining", "Nil"],
)
def test_every_way_of_saying_there_is_no_lining_rules_the_condition_out(value):
    gate = _gate(LINING, _fact("Internal lining", value))
    assert gate["state"] == conditions.NOT_SATISFIED


@pytest.mark.parametrize(
    "value",
    [
        "Not specified",
        "To be advised",
        "To be confirmed",
        "TBC",
        "Not provided by vendor",
        "Vendor to advise",
        "Unknown",
        "See datasheet 2",
    ],
)
def test_no_statement_yet_decides_nothing_either_way(value):
    assert _gate(LINING, _fact("Internal lining", value))["state"] == conditions.UNKNOWN


@pytest.mark.parametrize("value", ["No. 2 rubber", "No 4 grade rubber", "Rubber, 3 mm"])
def test_a_name_that_starts_with_no_is_a_lining_not_its_absence(value):
    assert (
        _gate(LINING, _fact("Internal lining", value))["state"] == conditions.SATISFIED
    )


@pytest.mark.parametrize(
    "value",
    [
        "Conventional / balanced bellows option",
        "Conventional or balanced",
        "Conventional (to be confirmed)",
        "Conventional and balanced",
        "Conventional & balanced",
        "Conventional, TBC",
        "Either conventional or pilot",
        "Conventional (optional balanced bellows)",
    ],
)
def test_a_value_that_offers_a_choice_or_is_unconfirmed_does_not_establish_the_condition(
    value,
):
    gate = _gate("a conventional valve", _fact("Valve type", value))
    assert gate["state"] == conditions.UNKNOWN


def test_the_unsettled_valve_is_an_engineers_question_not_a_breach():
    facts = [
        _fact("valve type", "Conventional or balanced"),
        _fact("built up back pressure", "14 %", raw_value="14", raw_unit="%"),
    ]
    verdict = comparison._compare(
        _req("a conventional valve"), facts[1], submittal_facts=facts
    )
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
