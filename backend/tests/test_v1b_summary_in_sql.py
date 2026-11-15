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


def test_V2_findings_of_old_runs_of_a_paper_are_not_counted_and_the_boundary_is_said():
    """V2 (audit): 87 runs over 5 papers counted 186,778 findings. Only the latest run of each paper counts, plus findings
    that belong to no run (added by hand)."""
    import uuid  # noqa: F401

    from tests.test_crs_endpoint import _run

    doc, other = _submittal("doc_x"), _submittal("doc_y", "y.pdf")
    old, new, other_run = _run(doc), _run(doc), _run(other)
    with db.connect() as conn:  # make "old" older than "new"
        conn.execute("UPDATE review_runs SET created_at = '2026-01-01T00:00:00Z' WHERE id = ?", (old,))
        conn.execute("UPDATE review_runs SET created_at = '2026-02-01T00:00:00Z' WHERE id = ?", (new,))
        conn.execute("UPDATE review_runs SET created_at = '2026-03-01T00:00:00Z' WHERE id = ?", (other_run,))
    for run_id, n in ((old, 5), (new, 2), (other_run, 1)):
        for _ in range(n):
            f = review.create({"document_id": doc if run_id != other_run else other, "category": "requirement_deviation",
                               "severity": "major", "requirement": "r", "finding": "f", "required_action": "a",
                               "compliance_status": "NON_COMPLIANT"}, created_by=None)
            with db.connect() as conn:
                conn.execute("UPDATE review_findings SET review_run_id = ? WHERE id = ?", (run_id, f["id"]))
    by_hand = review.create({"document_id": doc, "category": "requirement_deviation", "severity": "minor",
                             "requirement": "r", "finding": "f", "required_action": "a"}, created_by=None)
    assert by_hand["id"] and uuid
    out = deliverables_api.management_summary(scope=SimpleNamespace(allowed_document_ids=None))
    assert out["review_findings_total"] == 2 + 1 + 1  # newest run of doc, the one run of other, the hand-made one
    assert "2 papers" in out["findings_boundary"] and "earlier runs are not counted" in out["findings_boundary"]
    assert "findings that belong to no run" in out["findings_boundary"]
    # rule 5: a caller allowed ONE of the two papers is counted for that paper only, and the sentence says "1 paper"
    mine = deliverables_api.management_summary(scope=SimpleNamespace(allowed_document_ids=frozenset({doc})))
    assert mine["review_findings_total"] == 2 + 1  # the latest run of `doc` and the finding with no run (on `doc`)
    assert "of 1 paper," in mine["findings_boundary"]
    theirs = deliverables_api.management_summary(scope=SimpleNamespace(allowed_document_ids=frozenset({other})))
    assert theirs["review_findings_total"] == 1 and "of 1 paper," in theirs["findings_boundary"]
    nobody = deliverables_api.management_summary(scope=SimpleNamespace(allowed_document_ids=frozenset()))
    assert nobody["review_findings_total"] == 0 and "of 0 papers," in nobody["findings_boundary"]
