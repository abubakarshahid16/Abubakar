"""Order 95 piece 1: the CRS-first screen's tiers and `GET .../summary`.

Display only: every finding lands in one tier with one reason word, read from
stored fields; an unknown status is "needs you", never met; an AI guess stays a
guess until confirmed; a removed finding is counted, not tiered. Invented data.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import comparison, review_tiers
from app.db import connect
from app.main import app
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixtures
    _req,
    review_run,
    temp_storage,
)

T = review_tiers


def tier(**finding) -> tuple[str, str]:
    return T.tier_of(finding)


@pytest.mark.parametrize("finding, expected", [
    ({"compliance_status": "NON_COMPLIANT"}, (T.COMMENT, "does not meet")),
    ({"compliance_status": "MISSING_INFORMATION"}, (T.COMMENT, "not stated")),
    ({"compliance_status": "MISSING_INFORMATION", "reason_code": "requires_other_document"},
     (T.COMMENT, "other document")),
    ({"compliance_status": "NEEDS_ENGINEER_REVIEW"}, (T.NEEDS_YOU, "engineer check")),
    ({"compliance_status": "NEEDS_ENGINEER_REVIEW", "reason_code": "UNREAD_PAGES"},
     (T.NEEDS_YOU, "page not read")),
    # a row stored before #921 has no code: its rationale's leading code is read
    ({"compliance_status": "NEEDS_ENGINEER_REVIEW", "ai_rationale": "PAGE_READER_ONLY: p 3"},
     (T.NEEDS_YOU, "AI-read page")),
    ({"compliance_status": "CONDITIONAL"}, (T.NEEDS_YOU, "conditional")),
    ({"compliance_status": "COMPLIANT"}, (T.MET, "meets")),
    ({"compliance_status": "NOT_APPLICABLE"}, (T.MET, "not applicable")),
    ({"compliance_status": "NOT_IN_DOCUMENT_SCOPE"}, (T.MET, "not this document")),
])
def test_each_status_lands_in_one_tier_with_its_reason_word(finding, expected):
    assert T.tier_of(finding) == expected


def test_no_verdict_or_an_unknown_status_is_needs_you_never_met():
    assert tier(compliance_status=None) == (T.NEEDS_YOU, "no verdict")
    assert tier(compliance_status="SOMETHING_NEW") == (T.NEEDS_YOU, "no verdict")


def test_an_ai_finding_is_a_guess_until_an_engineer_confirms_it():
    for origin in ("ai_engineering_check", "web_standard_check"):
        assert tier(origin=origin, compliance_status="NON_COMPLIANT") == (T.NEEDS_YOU, "AI guess")
        assert tier(origin=origin, compliance_status="NON_COMPLIANT",
                    confirmed_by="u1") == (T.COMMENT, "does not meet")


def test_a_held_rule_and_an_unticked_safety_result_need_the_engineer():
    assert tier(trust_label="UNPROVEN", compliance_status="COMPLIANT") == (
        T.NEEDS_YOU, "rule not proven")
    assert tier(show_for_engineer_tick=1, compliance_status="COMPLIANT") == (
        T.NEEDS_YOU, "safety tick")
    assert tier(show_for_engineer_tick=1, compliance_status="COMPLIANT", confirmed_by="u1") == (
        T.MET, "meets")


def test_a_removed_finding_is_counted_not_tiered():
    out = T.summarise([
        {"id": "a", "compliance_status": "NON_COMPLIANT", "approval_status": "rejected"},
        {"id": "b", "compliance_status": "NON_COMPLIANT"},
    ])
    assert out["counts"] == {"comment": 1, "needs_you": 0, "met_or_not_applicable": 0,
                             "removed": 1, "total": 2}
    assert [r["finding_id"] for r in out["rows"]] == ["b"]


def test_rows_come_in_screen_order_tier_then_page_then_clause():
    out = T.summarise([
        {"id": "met", "compliance_status": "COMPLIANT", "contractor_page": 1},
        {"id": "nopage", "compliance_status": "NON_COMPLIANT"},
        {"id": "p2b", "compliance_status": "NON_COMPLIANT", "contractor_page": 2,
         "standard_clause": "5.2"},
        {"id": "p2a", "compliance_status": "NON_COMPLIANT", "contractor_page": 2,
         "standard_clause": "5.1"},
        {"id": "you", "compliance_status": "CONDITIONAL", "contractor_page": 1},
    ])
    assert [r["finding_id"] for r in out["rows"]] == ["p2a", "p2b", "nopage", "you", "met"]
    # null renders as nothing: no page stays None, never 0
    assert next(r for r in out["rows"] if r["finding_id"] == "nopage")["contractor_page"] is None


def test_the_summary_route_tiers_every_finding_of_a_stored_run(review_run):  # noqa: F811
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    findings = comparison.list_findings(run, allowed_document_ids=scope)
    assert findings, "the fixture run produced findings"
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    assert body["review_run_id"] == run
    assert body["boundary"]
    assert {r["finding_id"] for r in body["rows"]} == {f["id"] for f in findings}
    counts = body["counts"]
    assert counts["total"] == len(findings)
    assert counts["comment"] + counts["needs_you"] + counts["met_or_not_applicable"] == len(findings)
    for row in body["rows"]:
        stored = next(f for f in findings if f["id"] == row["finding_id"])
        assert (row["tier"], row["reason"]) == T.tier_of(stored)
    # "How this was reviewed" is the stored outcome's own fields, not a recount
    outcome = comparison.run_outcome(run, allowed_document_ids=scope)
    how = body["how_reviewed"]
    assert how["requirement_split"] == outcome["requirement_split"]
    assert how["page_coverage"] == outcome["page_coverage"]
    assert how["completeness"] == outcome["completeness"]


def test_a_removed_finding_leaves_the_rows_and_is_counted(review_run):  # noqa: F811
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    first = comparison.list_findings(run, allowed_document_ids=scope)[0]["id"]
    with connect() as conn:
        conn.execute("UPDATE review_findings SET approval_status = 'rejected' WHERE id = ?",
                     (first,))
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    assert first not in {r["finding_id"] for r in body["rows"]}
    assert body["counts"]["removed"] == 1


def test_an_unknown_run_is_404_and_writes_nothing(temp_storage):  # noqa: F811
    client = TestClient(app)
    assert client.get("/api/reviews/runs/nope/summary").status_code == 404
    assert client.get("/api/reviews/runs/nope/summary?x=1").status_code in (404, 422)
