"""Order 152.2 (PR #1201), old runs: the severity floor is applied where a
stored finding is READ, not only where a new one is written. Invented data.

MUTATION PROOF: read the stored word in `review._row`, or order by the bare
`severity` column, and these tests fail.
"""

from __future__ import annotations

from types import SimpleNamespace

from app import db, review, severity_rule
from app.api import deliverables as deliverables_api
from tests.test_crs_endpoint import _submittal, temp_db  # noqa: F401


def _stored(doc: str, status: str, severity: str, requirement: str) -> str:
    """A finding as an old run stored it: the severity word as it was then."""
    return review.create(
        {
            "document_id": doc,
            "category": "requirement_deviation",
            "severity": severity,
            "requirement": requirement,
            "finding": "f",
            "required_action": "a",
            "compliance_status": status,
        },
        created_by=None,
    )["id"]


def test_a_failed_finding_stored_minor_reads_major_and_sorts_with_the_majors():
    doc = _submittal()
    failed = _stored(doc, "NON_COMPLIANT", "minor", "failed")  # the OLDER row...
    blank = _stored(
        doc, "MISSING_INFORMATION", "minor", "blank"
    )  # ...so a bare-word order puts it after the blank
    major = _stored(doc, "COMPLIANT", "major", "other major")
    listed = review.list_findings(document_id=doc)
    by_id = {f["id"]: f for f in listed}
    assert by_id[failed]["severity"] == "major"
    assert by_id[blank]["severity"] == "minor"  # a blank stays minor
    order = [f["id"] for f in listed]
    assert order.index(failed) < order.index(blank) and order.index(
        major
    ) < order.index(blank)
    assert review.get(failed)["severity"] == "major"


def test_a_critical_failed_finding_still_sorts_first():
    doc = _submittal()
    _stored(doc, "NON_COMPLIANT", "minor", "failed")
    critical = _stored(doc, "NON_COMPLIANT", "critical", "critical")
    assert review.list_findings(document_id=doc)[0]["id"] == critical


def test_the_management_counts_read_the_floored_word():
    doc = _submittal()
    _stored(doc, "NON_COMPLIANT", "minor", "failed")
    _stored(doc, "MISSING_INFORMATION", "minor", "blank")
    summary = deliverables_api.management_summary(
        scope=SimpleNamespace(allowed_document_ids=None)
    )
    assert summary["findings_by_severity"] == {"major": 1, "minor": 1}


def test_the_sql_rank_and_the_python_rule_agree():
    """One home for the rule: the SQL rank orders exactly as the word reads."""
    doc = _submittal()
    for status in (
        "NON_COMPLIANT",
        "MISSING_INFORMATION",
        "NEEDS_ENGINEER_REVIEW",
        "COMPLIANT",
    ):
        for sev in ("critical", "major", "minor", "observation"):
            _stored(doc, status, sev, f"{status}/{sev}")
    rows = (
        db.connect()
        .execute(
            f"SELECT severity, compliance_status, {severity_rule.SQL_RANK} AS r FROM review_findings"
        )
        .fetchall()
    )
    assert len(rows) == 16
    for row in rows:
        word = severity_rule.effective_severity(dict(row))
        assert row["r"] == severity_rule.ORDER.index(word)
