"""#1655: a number a dash joins to a letter ("PN-63") is no STATED figure (the allowed side of a gate),
but it still COUNTS: a gate that counts numbers, or checks that a text brings no number its source
lacks, must see it, or a many-valued text looks single-valued and an invented figure gets through.
Invented values only."""

from __future__ import annotations

from app import (
    ai_engineering_check,
    claude_recheck,
    crs_wording,
    match_rules,
    numparse,
    rule_eval,
)


def test_number_keys_counts_a_joined_number_and_stated_keys_do_not():
    text = "within 10 bar per PN-63"
    assert numparse.number_keys(text) == {10.0, 63.0}
    assert numparse.stated_number_keys(text) == {10.0}


def test_the_rule_gate_does_not_take_a_joined_number_as_stated():
    assert not rule_eval.verify_numbers(
        {"rows": [{"from": 63.0}]}, "flange PN-63 rated"
    )


def test_several_values_counts_a_joined_number():
    requirement = {
        "requirement_text": "The design pressure shall not exceed 10 bar for PN-16 flanges",
        "raw_value": "10",
    }
    fact = {"field_name": "design pressure", "raw_value": "8"}
    assert (
        match_rules.model_pairing_doubt(requirement, fact) == match_rules.SEVERAL_VALUES
    )


def test_the_crs_lock_refuses_a_joined_number_the_row_does_not_carry():
    row = {
        "kind": "non_compliant",
        "comment": "Offered 10 bar is below the required 12 bar.",
        "standard_reference": "",
        "page_section": "",
    }
    assert (
        crs_wording.lock("Offered 10 bar is below the required 12 bar per PN-40.", row)
        == crs_wording.NUMBER_CHANGED
    )


def test_the_recheck_gate_refuses_a_joined_number_the_inputs_do_not_carry():
    finding = {
        "requirement_source_text": "Pressure shall not exceed 10 bar.",
        "value": "8",
        "unit": "bar",
    }
    proposal = {
        "agree": False,
        "quote": "not exceed 10 bar",
        "reason": "8 bar is within 10 bar per PN-63",
    }
    result = claude_recheck.accept(proposal, finding)
    assert result["accepted"] is None
    assert result["counts"] == {claude_recheck.Reason.NUMBER_NOT_IN_INPUTS.value: 1}


def test_the_engineering_check_refuses_a_joined_number_the_page_does_not_carry():
    item = {
        "topic": "pressure",
        "field": "design pressure",
        "observation": "Rated 10 bar per PN-63.",
        "action": "Confirm the rating.",
        "confidence": sorted(ai_engineering_check.CONFIDENCES)[0],
        "page": 1,
    }
    result = ai_engineering_check.accept(item, {1: "Design pressure 10 bar."}, {}, [])
    assert result["accepted"] is False
    assert result["reason"] == ai_engineering_check.Reason.NUMBER_NOT_ON_PAGE.value
