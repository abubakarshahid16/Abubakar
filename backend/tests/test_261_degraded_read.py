"""Order 261.2: a degraded AI reading never makes a verdict more confident. s2's clean vs broken
I-06 counts (facts 68 vs 39, conflicts 16 vs 4, checklist meets 81 vs 88, the
run summary saying nothing) as invented fixtures. No model, no network."""

from __future__ import annotations

import pytest

from app import absence, datasheets, db, degraded_read, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "degraded.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


# s2's REAL clean I-06 read (35B): the AI proposes far more than it can prove, so "refused > agreed"
# (117 > 58) is normal and says nothing about a broken engine.
CLEAN = {
    "engine": "local",
    "pages": 5,
    "pages_read": 5,
    "timed_out": [],
    "code_only": {},
    "refused_by_gate": 117,
    "agreed": 58,
    "facts_written": 68,
    "conflicts": 16,
}
# the same sheet when the engine failed under it: pages left to the code readers with an
# unusable answer, fewer facts, fewer conflicts
BROKEN = {
    **CLEAN,
    "code_only": {
        "2": "engine answer unusable (compute error)",
        "4": "engine answer unusable (x)",
    },
    "refused_by_gate": 46,
    "agreed": 24,
    "facts_written": 39,
    "conflicts": 4,
}


def passes(n):
    return [
        {
            "rule_id": f"P{i}",
            "status": "COMPLIANT",
            "checklist": True,
            "detail": "stated",
        }
        for i in range(n)
    ]


def meets(results):
    return sum(r["status"] == "COMPLIANT" for r in results)


@pytest.fixture
def reader(monkeypatch):
    def set_summary(summary):
        monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: summary)

    return set_summary


def test_a_clean_read_is_not_degraded():
    assert degraded_read.assess(CLEAN) is None


def test_a_page_with_an_unusable_engine_answer_is_degraded_and_says_the_counts():
    record = degraded_read.assess(BROKEN)
    assert record["why"] == ["failed_pages"] and record["failed_pages"] == 2
    assert "2 page(s) had an unusable or missing AI answer" in degraded_read.line(
        record
    )


def test_many_refusals_alone_are_not_a_broken_read():
    """s2's real clean reads refuse 117 and agree 58: that must not hold a single pass."""
    assert CLEAN["refused_by_gate"] > CLEAN["agreed"]
    assert degraded_read.assess(CLEAN) is None


def test_a_page_with_no_text_is_a_fact_about_the_page_not_a_failure():
    assert (
        degraded_read.assess({**CLEAN, "code_only": {"1": "no text on this page"}})
        is None
    )


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"timed_out": [2, 3]}, "timed_out"),
        ({"stopped": "time budget"}, "stopped"),
        ({"unavailable": "model not installed"}, "unavailable"),
    ],
)
def test_a_timeout_a_stop_or_an_unavailable_reader_is_degraded(change, why):
    assert degraded_read.assess({**CLEAN, **change})["why"] == [why]


def test_an_ai_reader_that_was_not_asked_is_not_degraded():
    assert degraded_read.assess({"engine": "off", "pages": 3}) is None
    assert degraded_read.assess(None) is None


def test_the_broken_read_gives_no_more_meets_than_the_clean_one(reader):
    reader(CLEAN)
    clean = degraded_read.hold(passes(81), "doc")
    reader(BROKEN)
    broken = degraded_read.hold(passes(88), "doc")
    assert meets(clean) == 81
    assert meets(broken) == 0 <= meets(clean)
    assert {r["status"] for r in broken} == {"NEEDS_ENGINEER_REVIEW"}
    assert (
        "degraded" in broken[0]["detail"]
        and "2 page(s) had an unusable or missing AI answer" in broken[0]["detail"]
    )


def test_only_checklist_passes_are_held_and_failures_stay_failures(reader):
    reader(BROKEN)
    results = [
        {"rule_id": "A", "status": "NON_COMPLIANT", "checklist": True, "detail": "x"},
        {
            "rule_id": "B",
            "status": "MISSING_INFORMATION",
            "checklist": True,
            "detail": "x",
        },
        {"rule_id": "C", "status": "COMPLIANT", "detail": "a consistency pair"},
        {"rule_id": "D", "status": "COMPLIANT", "checklist": True, "detail": "x"},
    ]
    held = {r["rule_id"]: r["status"] for r in degraded_read.hold(results, "doc")}
    assert held == {
        "A": "NON_COMPLIANT",
        "B": "MISSING_INFORMATION",
        "C": "COMPLIANT",
        "D": "NEEDS_ENGINEER_REVIEW",
    }


def test_a_clean_read_changes_nothing(reader):
    reader(CLEAN)
    results = passes(3)
    assert degraded_read.hold(results, "doc") == results


def test_the_split_carries_the_record_and_the_reader_summary(reader):
    reader(BROKEN)
    split = degraded_read.with_reader({"checked": 3}, "doc")
    assert split["reader"] == BROKEN and split["degraded_read"]["why"] == [
        "failed_pages"
    ]
    reader(CLEAN)
    clean = degraded_read.with_reader({"checked": 3}, "doc")
    assert "degraded_read" not in clean and clean["reader"] == CLEAN


def test_the_crs_banner_lists_a_degraded_read_as_a_part_that_could_not_be_trusted():
    record = degraded_read.assess(BROKEN)
    outcome = {
        "requirement_split": {"degraded_read": record},
        "unchecked_counts": {"not_compared": 0, "not_applied": 0, "checked": 5},
    }
    parts = absence.unchecked_parts(run_status="completed", outcome=outcome)
    assert [p["part"] for p in parts] == ["degraded_read"]
    assert "REVIEW INCOMPLETE" in absence.notice_for(parts)
    assert absence.unchecked_parts(run_status="completed", outcome={}) == []


def _checklist_findings(run_id):
    from app import db

    rows = db.connect().execute(
        "SELECT compliance_status FROM review_findings WHERE review_run_id = ?"
        " AND origin = 'datasheet_check'",
        (run_id,),
    )
    return [r["compliance_status"] for r in rows]


def _review_with(summary, monkeypatch):
    from tests.test_746_checklist_governs import (
        _review,
    )

    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: summary)
    result, _stored, _ids = _review("Pressure Safety Valve")
    from app import db

    run = db.connect().execute("SELECT id FROM review_runs").fetchone()["id"]
    return result, _checklist_findings(run)


def test_a_whole_review_on_a_degraded_read_holds_every_checklist_pass(monkeypatch):
    clean_result, clean = _review_with(CLEAN, monkeypatch)
    assert (
        "COMPLIANT" in clean
        and "degraded_read" not in clean_result["requirement_split"]
    )
    from tests.test_746_checklist_governs import _review_again

    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda _doc: BROKEN)
    result, _s, _i = _review_again("Pressure Safety Valve")
    from app import db

    run = db.connect().execute("SELECT id FROM review_runs").fetchone()["id"]
    broken = _checklist_findings(run)
    assert "COMPLIANT" not in broken and "NEEDS_ENGINEER_REVIEW" in broken
    assert len(broken) == len(clean)
    assert result["requirement_split"]["degraded_read"]["why"] == ["failed_pages"]
