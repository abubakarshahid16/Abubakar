"""Order 152.2, severity: a failed requirement is never filed "minor".

Plain words: "minor" means a blank, or an item nobody has decided yet. It never
describes a requirement the datasheet failed. Invented data only; no model, no
socket.

Mutations: M1201-01 .. M1201-05 (scripts/mutations/pr1201_severity_floor.py).
"""

from __future__ import annotations

import json

import pytest

from app import comparison, db, severity_rule
from app import datasheet_checks as dc
from app.crs_mapping import build_crs_rows, row_severity
from tests.test_crs_endpoint import _submittal, temp_db  # noqa: F401


def _result(severity, status=dc.NON_COMPLIANT, **over):
    return {
        "rule_id": "DS-C1",
        "status": status,
        "detail": "a detail",
        "text": "a rule shall hold",
        "severity": severity,
        "checklist": True,
        "fact_id": "fact-1",
        "equipment_tag": "V-101",
        "field": "Design pressure",
        "value": "5 bar",
        "page": 2,
        "standard": "STD-A",
        "clause": "1.1",
        **over,
    }


def _stored(results):
    doc = _submittal()
    return [
        # The raw column: `review.get` floors on read (PR #1201), which would hide the write.
        db.connect()
        .execute("SELECT severity FROM review_findings WHERE id = ?", (w["id"],))
        .fetchone()[0]
        for w in dc.store("run-1", doc, results, pages_read={})
    ]


def _finding(severity, status="NON_COMPLIANT", **over):
    return {
        "id": f"f-{severity}-{status}",
        "compliance_status": status,
        "severity": severity,
        "origin": dc.ORIGIN,
        "standard_name": "SPEC-X.pdf",
        "standard_clause": "5.1",
        "standard_page": 7,
        "requirement_source_text": "The pressure shall not exceed 10 barg.",
        "crs_field_label": "PRESSURE",
        "fact_id": "f",
        "equipment_tag": "V-1",
        "contractor_evidence_text": "12 barg",
        "contractor_page": 2,
        **over,
    }


def test_failed_checklist_item_with_minor_item_severity_is_stored_major(temp_db):  # noqa: F811
    assert _stored([_result("minor")]) == ["major"]


def test_critical_item_stays_critical_when_it_fails(temp_db):  # noqa: F811
    assert _stored([_result("critical")]) == ["critical"]


def test_old_stored_minor_on_a_failed_finding_reads_major_on_the_crs_row():
    for old in ("minor", "", "unknown", None, "observation"):
        [row] = build_crs_rows([_finding(old)], [], "ds.pdf")
        assert row["severity"] == "major", old


def test_row_severity_is_the_worst_of_the_group():
    group = [
        _finding("major", id="a"),
        _finding("critical", id="b"),
        _finding("minor", id="c"),
    ]
    assert row_severity(group) == "critical"


def test_row_severity_is_not_the_first():
    group = [_finding("minor", id="a"), _finding("critical", id="b")]
    assert row_severity(group) == "critical"
    assert row_severity([_finding("", status="MISSING_INFORMATION")]) == ""


def test_blank_and_engineer_to_check_stay_minor_and_say_so():
    assert "never describes a requirement the datasheet FAILED" in severity_rule.__doc__
    blank = _finding("minor", status="MISSING_INFORMATION")
    assert severity_rule.effective_severity(blank) == "minor"
    check = _finding("observation", status="NEEDS_ENGINEER_REVIEW")
    assert severity_rule.effective_severity(check) == "minor"
    assert (
        severity_rule.effective_severity(_finding("observation", status="COMPLIANT"))
        == "observation"
    )
    assert severity_rule.stored_severity("MISSING_INFORMATION") == "minor"
    assert severity_rule.stored_severity("COMPLIANT") == "observation"


def test_every_checklist_failure_in_the_json_is_at_least_major(temp_db):  # noqa: F811
    checklists = json.loads(dc.RULES_PATH.read_text(encoding="utf-8"))["checklists"]
    items = [i for v in checklists.values() if isinstance(v, dict) for i in v["items"]]
    assert len(items) > 20
    assert {i.get("severity", "minor") for i in items} >= {
        "minor"
    }  # the case that mattered
    stored = _stored(
        [_result(i.get("severity", "minor"), rule_id=i["id"]) for i in items]
    )
    assert len(stored) == len(items)
    assert set(stored) <= {"major", "critical"}


@pytest.mark.parametrize("status", [comparison.NON_COMPLIANT, None, "A_FUTURE_STATUS"])
def test_comparison_severity_table_never_lists_non_compliant_below_major(status):
    assert (
        comparison.SEVERITY_BY_STATUS.get(comparison.NON_COMPLIANT, "major") == "major"
    )
    assert comparison._default_severity(status) == "major"
