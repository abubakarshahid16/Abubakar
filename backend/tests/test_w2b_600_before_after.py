"""#600: the before/after acceptance tool counts honestly - every share with
its denominator, and a CRS row resting on a requirement the run's own scope
ledger says does not apply is counted, never hidden. Invented data only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import accept_review_before_after as a  # noqa: E402

FINDINGS = [
    {"id": "f1", "requirement_id": "r1", "compliance_status": "MISSING_INFORMATION"},
    {"id": "f2", "requirement_id": "r2", "compliance_status": "NEEDS_ENGINEER_REVIEW"},
    {"id": "f3", "requirement_id": "r3", "compliance_status": "NEEDS_ENGINEER_REVIEW"},
    {"id": "f4", "requirement_id": None, "compliance_status": None},
]


def test_the_needs_engineer_share_carries_its_denominator():
    out = a.summarise(FINDINGS, [], {})
    assert out["checks"] == 4
    assert out["needs_engineer"] == {"count": 2, "of": 4}
    assert out["checks_by_status"] == {"MISSING_INFORMATION": 1, "NEEDS_ENGINEER_REVIEW": 2, "none": 1}


def test_a_crs_row_on_a_requirement_that_does_not_apply_is_counted():
    rows = [{"finding_id": "f1", "kind": "missing_information"},
            {"finding_id": "f2", "kind": "question"},
            {"finding_id": "f4", "kind": "datasheet_check"}]
    decisions = {"r1": "checked", "r2": "does_not_apply"}
    out = a.summarise(FINDINGS, rows, decisions)
    assert out["crs_rows"] == 3
    assert out["crs_rows_by_kind"] == {"missing_information": 1, "question": 1, "datasheet_check": 1}
    assert out["crs_rows_on_a_requirement_that_does_not_apply"] == 1
    # every row on a requirement that applies: none counted
    assert a.summarise(FINDINGS, rows, {"r1": "checked", "r2": "checked"})[
        "crs_rows_on_a_requirement_that_does_not_apply"] == 0


def test_it_refuses_a_live_shaped_database_path(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    with pytest.raises(SystemExit, match="refusing"):
        a.main(["--run", "x", "--db", f"before={live}"])
    assert not live.exists()
