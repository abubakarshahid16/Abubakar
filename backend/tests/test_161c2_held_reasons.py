"""Order 161 C (163.4): every finding held for the engineer has a reason that
can be counted, and the run summary says them. Invented findings only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import comparison, held_reasons
from app.main import app
from tests.test_139_crs_numbers_merge import (
    _add_blanks,  # noqa: F401 - keeps the world fixture's helper
)
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

HELD = comparison.NEEDS_ENGINEER_REVIEW


def _held(**over) -> dict:
    return {"compliance_status": HELD, "approval_status": "pending", **over}


def test_a_stored_reason_code_is_the_reason():
    assert (
        held_reasons.reason_of(_held(reason_code="UNREAD_PAGES", fact_id="f1"))
        == "UNREAD_PAGES"
    )


def test_the_programs_own_leading_code_is_the_reason_when_none_is_stored():
    for code in held_reasons.LEADING:
        assert held_reasons.reason_of(_held(ai_rationale=f"{code}: something")) == code


def test_a_plain_sentence_is_named_by_what_the_finding_shows():
    plain = "the submitted value could not be read as a quantity"
    assert (
        held_reasons.reason_of(_held(ai_rationale=plain))
        == held_reasons.NO_FIELD_PAIRED
    )
    assert (
        held_reasons.reason_of(_held(ai_rationale=plain, fact_id="f1"))
        == held_reasons.VALUE_NOT_DECIDED
    )
    assert (
        held_reasons.reason_of(_held()) == held_reasons.NO_FIELD_PAIRED
    )  # no rationale at all


def test_the_counts_cover_exactly_the_held_findings_and_never_lose_one():
    findings = [
        _held(reason_code="UNREAD_PAGES"),
        _held(reason_code="UNREAD_PAGES"),
        _held(ai_rationale="plain words", fact_id="f"),
        _held(ai_rationale="plain words"),
        _held(approval_status="rejected"),  # removed by an engineer: not counted
        {"compliance_status": "COMPLIANT"},  # not held
        {"compliance_status": "NON_COMPLIANT", "reason_code": "x"},
    ]
    got = held_reasons.counts(findings)
    assert got == {
        "UNREAD_PAGES": 2,
        held_reasons.NO_FIELD_PAIRED: 1,
        held_reasons.VALUE_NOT_DECIDED: 1,
    }
    assert sum(got.values()) == 4
    assert next(iter(got)) == "UNREAD_PAGES"  # most common first


def test_every_leading_code_is_a_constant_of_the_comparison_module():
    names = {
        getattr(comparison, n)
        for n in dir(comparison)
        if isinstance(getattr(comparison, n), str)
    }
    assert set(held_reasons.LEADING) <= names


@pytest.mark.usefixtures("temp_storage")
def test_the_run_summary_carries_the_held_reasons(world):  # noqa: F811
    _sub, run, _scope = world
    response = TestClient(app).get(f"/api/reviews/runs/{run}/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["held_reasons"], dict)
    held = sum(1 for r in body["rows"] if r["compliance_status"] == HELD)
    assert sum(body["held_reasons"].values()) == held
