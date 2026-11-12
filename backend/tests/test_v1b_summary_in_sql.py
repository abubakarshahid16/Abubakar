"""V1b: the management summary counts findings in SQL; the numbers equal the old read-everything count. Invented data.

MUTATION: drop the escalation test or the severity word in `finding_query.summary_counts` and these fail.
"""

from __future__ import annotations

from types import SimpleNamespace

from app import db, finding_query, review
from app.api import deliverables as deliverables_api
from tests.test_crs_endpoint import _submittal, temp_db  # noqa: F401


def _make(doc, status, severity, state, level):
    f = review.create(
        {"document_id": doc, "category": "requirement_deviation", "severity": severity, "requirement": "r",
         "finding": "f", "required_action": "a", "compliance_status": status, "escalation_level": level},
        created_by=None,
    )
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET status = ? WHERE id = ?", (state, f["id"]))


def _old(allowed):
    findings = review.list_findings(allowed_document_ids=allowed)
    return {
        "total": len(findings),
        "by_severity": {s: sum(1 for f in findings if f["severity"] == s) for s in {f["severity"] for f in findings}},
        "by_status": {s: sum(1 for f in findings if f["status"] == s) for s in {f["status"] for f in findings}},
        "escalated": sum(1 for f in findings if f["escalation_level"] > 0),
    }


def test_sql_counts_equal_the_old_python_counts():
    doc, other = _submittal("doc_a"), _submittal("doc_b", "b.pdf")
    for status in ("NON_COMPLIANT", "MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW", "COMPLIANT"):
        for sev in ("critical", "major", "minor", "observation"):
            for level in (0, 2):
                _make(doc, status, sev, "open" if level == 0 else "confirmed", level)
    _make(other, "NON_COMPLIANT", "minor", "open", 1)
    for allowed in (None, frozenset({doc}), frozenset({other}), frozenset({doc, other})):
        assert finding_query.summary_counts(allowed) == _old(allowed)
    assert finding_query.summary_counts(None)["escalated"] == 17
    assert finding_query.summary_counts(frozenset()) == {"total": 0, "by_severity": {}, "by_status": {}, "escalated": 0}


def test_the_route_answers_the_same_numbers():
    doc = _submittal()
    _make(doc, "NON_COMPLIANT", "minor", "open", 1)
    out = deliverables_api.management_summary(scope=SimpleNamespace(allowed_document_ids=None))
    old = _old(None)
    assert out["review_findings_total"] == old["total"] == 1
    assert out["findings_by_severity"] == old["by_severity"] == {"major": 1}
    assert out["escalated_findings"] == 1
