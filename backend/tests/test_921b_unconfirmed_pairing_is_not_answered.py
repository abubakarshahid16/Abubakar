"""#921 point 1 (PF2): completeness counts a requirement as answered only by a
field that was PAIRED with confidence. A pairing a model named (held for an
engineer) or the AI matcher's low-confidence pairing is a question. Invented
findings only."""
from __future__ import annotations

import pytest

from app import comparison


def _f(rid, status, *, fact="f1", method="containment", rationale="ok"):
    return {"requirement_id": rid, "compliance_status": status, "fact_id": fact,
            "match_method": method, "ai_rationale": rationale}


def test_a_confident_pairing_is_answered():
    assert comparison._required_and_answered([_f("r1", "COMPLIANT")]) == (1, 1)


def test_a_model_named_field_pairing_is_not_an_answer():
    assert comparison._required_and_answered(
        [_f("r1", "NEEDS_ENGINEER_REVIEW", method=comparison.METHOD_FIELD_NAME)]) == (1, 0)


def test_a_held_ai_matcher_pairing_is_not_an_answer_but_a_decided_one_is():
    held = _f("r1", "NEEDS_ENGINEER_REVIEW", method=comparison.METHOD_MODEL_CHOICE)
    decided = _f("r2", "COMPLIANT", method=comparison.METHOD_MODEL_CHOICE)
    assert comparison._required_and_answered([held, decided]) == (2, 1)


def test_one_confident_finding_still_answers_a_requirement_judged_for_several_items():
    assert comparison._required_and_answered([
        _f("r1", "NEEDS_ENGINEER_REVIEW", method=comparison.METHOD_FIELD_NAME, fact="a"),
        _f("r1", "COMPLIANT", fact="b")]) == (1, 1)


def test_an_unconfirmed_pairing_lowers_the_gate_that_approval_needs():
    findings = [_f(f"r{i}", "NEEDS_ENGINEER_REVIEW", method=comparison.METHOD_FIELD_NAME) for i in range(10)]
    required, answered = comparison._required_and_answered(findings)
    assert (required, answered) == (10, 0)
