"""Order 260.1: ONE meaning of "checked". A requirement is checked only when a datasheet value was
compared with its limit (met, not met, conditional). A requirement that reached the comparison
and ended as missing information, an engineer's question or "another document gives it" applies
but is NOT checked; the comparison finding it does not apply puts it outside the denominator.
`scope_ledger.group_of` is the one rule; the split, the clause coverage and the approval guard
read it. Invented findings only; no model, no network."""

from __future__ import annotations

import pytest

from app import clause_coverage, comparison, requirement_split, scope_ledger

COMPARED = ("COMPLIANT", "NON_COMPLIANT", "CONDITIONAL")
NOT_COMPARED = (
    "MISSING_INFORMATION",
    "NEEDS_ENGINEER_REVIEW",
    "NOT_IN_DOCUMENT_SCOPE",
    None,
    "A_STATUS_NOBODY_DEFINED",
)
SUFFICIENT = {
    "sufficient": True,
    "fields_read": 100,
    "fields_estimated": 100,
    "extraction_coverage": 1.0,
}


@pytest.mark.parametrize("status", COMPARED)
def test_a_value_compared_with_its_limit_is_checked(status):
    assert scope_ledger.group_of(status)[0] == scope_ledger.CHECKED


@pytest.mark.parametrize("status", NOT_COMPARED)
def test_a_requirement_that_reached_the_comparison_without_a_compared_value_is_not_checked(
    status,
):
    assert scope_ledger.group_of(status)[0] == scope_ledger.APPLIES_NOT_CHECKED


def test_the_comparison_finding_it_does_not_apply_is_outside_the_denominator():
    assert scope_ledger.group_of("NOT_APPLICABLE")[0] == scope_ledger.DOES_NOT_APPLY


def _reqs(n):
    return [
        {"id": f"r{i}", "requirement_text": f"requirement number {i}"} for i in range(n)
    ]


def test_the_split_counts_only_compared_requirements_as_checked():
    statuses = [*COMPARED, "MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"]
    statuses += ["NOT_IN_DOCUMENT_SCOPE"] * 3 + ["NOT_APPLICABLE"]
    reqs = _reqs(len(statuses))
    split = requirement_split.build(
        reqs, [], [], status_of={r["id"]: s for r, s in zip(reqs, statuses)}
    )
    assert split["checked"] == 3
    assert split["applies_not_checked"] == 5
    assert split["does_not_apply"] == 1
    # of the 8 that apply, 5 were not compared
    assert split["unchecked_share"] == pytest.approx(5 / 8)
    reasons = {r["reason"] for r in split["applies_not_checked_reasons"]}
    assert "it asks for evidence another document gives" in reasons


def test_a_requirement_with_no_finding_is_an_engineers_question_not_a_check():
    split = requirement_split.build(_reqs(2), [], [], status_of={})
    assert (split["checked"], split["applies_not_checked"]) == (0, 2)


def test_a_run_whose_requirements_all_ended_as_another_document_cannot_be_approved():
    """The safety case: 1 value compared, 9 requirements that only asked for another document.
    Before, all 10 counted as checked, so the guard saw no unchecked part and an approval stood."""
    reqs = _reqs(10)
    status_of = {r["id"]: "NOT_IN_DOCUMENT_SCOPE" for r in reqs}
    status_of["r0"] = "COMPLIANT"
    split = requirement_split.build(reqs, [], [], status_of=status_of)
    counts = {
        "not_compared": split["applies_not_checked"],
        "not_applied": split["does_not_apply"],
        "checked": split["checked"],
    }
    met = [{"compliance_status": comparison.COMPLIANT}]
    result = comparison.recommend_code(met, SUFFICIENT, unchecked_counts=counts)
    assert result["code"] == comparison.CODE_MANUAL
    assert (
        "9 of 10 requirements that apply to this submittal were not checked"
        in result["reason"]
    )


def test_the_clause_coverage_agrees_with_the_ledger_on_every_reason():
    for code, (state, _words) in scope_ledger.REASONS.items():
        pf4 = clause_coverage.STATE_OF[code]
        if state == scope_ledger.CHECKED:
            assert pf4 == clause_coverage.CHECKED, code
        else:
            assert pf4 != clause_coverage.CHECKED, code
    assert (
        clause_coverage.STATE_OF["missing_information"] == clause_coverage.NOT_CHECKED
    )
    assert clause_coverage.STATE_OF["not_applicable"] == clause_coverage.DOES_NOT_APPLY
