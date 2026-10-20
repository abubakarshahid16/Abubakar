"""Order 152.2: the sheet's counts come from ONE place, in rows, each with its unit.

`review_counts.sheet_counts` counts what the CRS sheet shows (rows) from the
run's findings, the file's grouping and the tier of each finding. The run
summary sends it as `sheet`. A row of 13 blanks is ONE comment and 13
findings, and the two numbers are never mixed.

Synthetic findings only (invented fields and clauses).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, comparison, main, review_counts, review_tiers
from app.main import app
from tests.test_139_crs_numbers_merge import _add_blanks
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

FACTS = review_tiers.RunFacts()


def _f(fid, status, **extra) -> dict:
    return {"id": fid, "compliance_status": status, **extra}


def _counts(findings, groups):
    return review_counts.sheet_counts(findings, FACTS, groups)


def test_many_findings_on_one_row_are_one_comment_and_many_findings():
    findings = [
        _f(f"b{i}", "MISSING_INFORMATION", standard_document_id="s") for i in range(13)
    ]
    findings.append(_f("x", "NON_COMPLIANT"))
    groups = {f"b{i}": {"crs_group": "field:a"} for i in range(13)}
    groups["x"] = {"crs_group": "req:x"}
    got = _counts(findings, groups)
    assert got["comments"] == 2
    assert got["findings_in_comments"] == 14
    assert got["findings"] == 14


def test_a_row_takes_the_worst_tier_of_its_findings():
    findings = [
        _f("a", "COMPLIANT"),
        _f("b", "NON_COMPLIANT"),
        _f("c", "NEEDS_ENGINEER_REVIEW"),
    ]
    groups = {k: {"crs_group": "g"} for k in "abc"}
    got = _counts(findings, groups)
    assert (got["comments"], got["needs_you"], got["met"]) == (1, 1, 0)


def test_a_met_row_is_not_a_comment():
    got = _counts([_f("a", "COMPLIANT")], {"a": {"crs_group": "g"}})
    assert (got["comments"], got["met"], got["findings_in_comments"]) == (0, 1, 0)


def test_a_finding_with_no_group_is_a_row_of_its_own():
    got = _counts([_f("a", "NON_COMPLIANT"), _f("b", "NON_COMPLIANT")], {})
    assert got["comments"] == 2


def test_removed_chat_page_note_and_review_note_findings_are_on_no_row():
    findings = [
        _f("r", "NON_COMPLIANT", approval_status="rejected"),
        _f("c", "NON_COMPLIANT", origin="chat"),
        _f(
            "p",
            "NEEDS_ENGINEER_REVIEW",
            ai_rationale=comparison.UNREAD_PAGES + ": page 3",
        ),
        _f("n", "NEEDS_ENGINEER_REVIEW"),
        _f("k", "NON_COMPLIANT"),
    ]
    got = _counts(findings, {"n": {"crs_note": True}})
    assert got["comments"] == 1
    assert (got["removed"], got["review_notes"], got["findings"]) == (1, 1, 5)


def test_no_grouping_is_not_known_not_zero():
    assert review_counts.sheet_counts([_f("a", "NON_COMPLIANT")], FACTS, None) is None


def _summary(run) -> dict:
    response = TestClient(app).get(f"/api/reviews/runs/{run}/summary")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_summary_sheet_equals_the_files_rows(world):  # noqa: F811
    _sub, run, scope = world
    _add_blanks(run, ("4.1", "6.2", "7.7"))
    body = _summary(run)
    sheet = body["sheet"]
    file_rows, *_ = main._crs_content(
        run, access.AccessScope(user_id=None, allowed_document_ids=scope)
    )
    finding_rows = [r for r in file_rows if r.get("finding_ids")]
    assert sheet["comments"] == len(finding_rows)
    assert sheet["findings_in_comments"] == sum(
        len(r["finding_ids"]) for r in finding_rows
    )
    assert sheet["findings"] == body["counts"]["total"]
    assert sheet["removed"] == body["counts"]["removed"]
    # three blanks are ONE row: the rows and the findings are different numbers
    assert sheet["findings_in_comments"] > sheet["comments"]


def test_the_shared_case_table_gives_the_expected_counts():
    """`contracts/fixtures/sheet_count_cases.json` is the ONE list the server
    and the screen (`crs/sheetCounts.parity.test.ts`) both pass."""
    import json
    from pathlib import Path

    table = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts/fixtures/sheet_count_cases.json"
        ).read_text(encoding="utf-8")
    )
    for case in table["cases"]:
        findings = [{**table["base_finding"], **f} for f in case["findings"]]
        assert (
            review_counts.sheet_counts(findings, FACTS, case["groups"])
            == case["expected"]
        ), case["name"]
