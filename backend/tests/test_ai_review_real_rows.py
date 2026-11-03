"""Lane 6: the AI review pass never removes a Fail, tested on rows `build_crs_rows` really builds from stored findings.

A datasheet self-check that FAILED has the row kind `datasheet_check`, not `non_compliant`; the verifier must still read
it as a Fail (from the carried result and severity), and `apply` re-derives the verdict from the source finding.
Invented data only.
"""

from __future__ import annotations

import pytest

from app import ai_review_proposals as arp
from app import crs_mapping

PAGE = "Tag V-1  Design pressure 12 barg  MAWP 14 barg"


def _finding(status, origin="datasheet_check", severity="major", fid=None, **over):
    return {
        "id": fid or f"f-{origin}-{status}",
        "compliance_status": status,
        "severity": severity,
        "origin": origin,
        "standard_name": "SPEC-X.pdf",
        "standard_clause": "5.1",
        "standard_page": 7,
        "requirement_source_text": "The pressure shall not exceed 10 barg.",
        "crs_field_label": "PRESSURE",
        "fact_id": "f",
        "equipment_tag": "V-1",
        "contractor_evidence_text": "12 barg",
        "contractor_page": 1,
        **over,
    }


def _row(finding):
    rows = crs_mapping.build_crs_rows([finding], [], "ds.pdf")
    assert len(rows) == 1
    return rows[0]


def _remove(row):
    return {
        "id": "p1",
        "type": "remove",
        "row_key": row["comment_key"],
        "page": 1,
        "basis": "context",
        "value": "12 barg",
        "reason": "Looks wrong in context.",
        "confidence": "medium",
        "evidence": [{"page": 1, "quote": "Tag V-1  Design pressure 12 barg"}],
    }


def _ctx(row):
    return arp.Context(pages={1: PAGE}, rows={row["comment_key"]: row}, held={})


def test_a_failed_datasheet_self_check_is_a_datasheet_check_row_that_carries_its_result():
    row = _row(_finding("NON_COMPLIANT"))
    assert row["row_kind"] == "datasheet_check"  # the mapping's own label
    assert row["compliance_status"] == "NON_COMPLIANT" and row["severity"] == "major"


@pytest.mark.parametrize("severity", ["major", "critical", "minor", "observation", ""])
def test_a_failed_datasheet_self_check_is_never_removed_whatever_its_stored_severity(
    severity,
):
    row = _row(_finding("NON_COMPLIANT", severity=severity))
    verdict = arp.verify(_remove(row), _ctx(row))
    assert not verdict.accepted and verdict.reason == arp.Reason.FAIL_KEPT.value


def test_a_datasheet_check_held_for_the_engineer_is_the_only_one_that_can_go():
    row = _row(_finding("NEEDS_ENGINEER_REVIEW", severity="minor"))
    assert row["row_kind"] == "datasheet_check"
    assert arp.verify(_remove(row), _ctx(row)).accepted
    # a datasheet check with no carried result is not removable at all
    bare = {k: v for k, v in row.items() if k != "compliance_status"}
    assert not arp.verify(_remove(bare), _ctx(bare)).accepted
    # nor is a major one, whatever its result says
    major = dict(row, severity="major")
    assert arp.verify(_remove(major), _ctx(major)).reason == arp.Reason.FAIL_KEPT.value


@pytest.mark.parametrize(
    "kind", ["ai_engineering_check", "datasheet_check", "needs_engineer_review"]
)
def test_a_row_built_from_a_non_compliant_finding_is_a_fail_whatever_its_label(kind):
    for status in ("NON_COMPLIANT", "non-compliant", "Non Compliant"):
        row = dict(
            _row(_finding("NON_COMPLIANT")), row_kind=kind, compliance_status=status
        )
        assert arp.verify(_remove(row), _ctx(row)).reason == arp.Reason.FAIL_KEPT.value


def test_a_needs_engineer_review_row_built_from_a_question_can_go_and_a_breach_cannot():
    question = _row(
        _finding("NEEDS_ENGINEER_REVIEW", origin="review", severity="minor")
    )
    breach = _row(_finding("NON_COMPLIANT", origin="review"))
    assert question["row_kind"] == "needs_engineer_review"
    assert breach["row_kind"] == "non_compliant"
    assert arp.verify(_remove(question), _ctx(question)).accepted
    assert (
        arp.verify(_remove(breach), _ctx(breach)).reason == arp.Reason.FAIL_KEPT.value
    )
