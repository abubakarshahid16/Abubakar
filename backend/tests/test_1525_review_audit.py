"""#1525: one machine-written AUDIT.md + AUDIT.json per review run, behind
REVIEW_AUDIT_REPORT_ENABLED (off by default). Invented documents only.

What must hold: off = nothing written; on = both files, whose counts equal the
review trace's counts for the same run (pages, decided, quotes, CRS rows);
a missing figure reads "not recorded" and is never 0; a failed AI step is
listed as failed with no verdict changed; a failure writing the audit never
breaks or changes the review.
"""

from __future__ import annotations

import json

import pytest

from app import access, review_audit, review_jobs, review_trace
from app.config import settings
from app.db import connect
from tests.test_p3_review_jobs import W, _enqueue, temp_storage, world  # noqa: F401 - fixtures


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "review_audit_dir", str(tmp_path / "proof"))
    return tmp_path / "proof"


def _scope(world):
    return access.AccessScope(user_id=None, allowed_document_ids=world["scope"])


def _review(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _files(audit_dir):
    return sorted(audit_dir.rglob("AUDIT.*")) if audit_dir.exists() else []


def _json(audit_dir):
    return json.loads(
        next(f for f in _files(audit_dir) if f.suffix == ".json").read_text()
    )


def test_the_switch_is_off_by_default_and_nothing_is_written(world, audit_dir):
    assert settings.review_audit_report_enabled is False
    _review(world)
    assert _files(audit_dir) == []


def test_a_review_with_the_switch_on_writes_both_files_in_the_dated_run_folder(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    files = _files(audit_dir)
    assert [f.name for f in files] == ["AUDIT.json", "AUDIT.md"]
    assert files[0].parent.name.endswith(f"-{run_id}")
    assert files[0].parent.name[:4].isdigit()


def test_the_counts_equal_the_trace_counts_of_the_same_run(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    audit = _json(audit_dir)
    steps = {s["step"]: s for s in review_trace.build(run_id, _scope(world))["steps"]}
    assert audit["run"]["id"] == run_id and audit["run"]["document_id"] == world["sub"]
    assert audit["rules"]["rows_total"] == len(audit["rules"]["rows"]) > 0
    decide = steps["DECIDE"]["counts"]
    assert audit["rules"]["verdict_counts"] == {
        review_audit.VERDICT.get(code, code): decide[label]
        for code, label in review_trace._DECISIONS
        if decide.get(label)
    }
    assert audit["crs"]["rows_exported"] == steps["CRS"]["counts"]["rows"]
    assert audit["standards"]["applied_count"] == steps["STANDARDS"]["counts"]["chosen"]
    assert (
        audit["standards"]["cited_not_in_library_count"]
        == steps["STANDARDS"]["counts"]["cited_not_held"]
    )
    assert "documents the requester may read" in audit["boundary"]


def test_markdown_and_json_carry_the_same_figures(world, audit_dir, monkeypatch):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    md = next(f for f in _files(audit_dir) if f.suffix == ".md").read_text()
    audit = _json(audit_dir)
    assert f"rules compared: {audit['rules']['rows_total']}" in md
    for heading in (
        "## 1. Run",
        "## 2. Pages",
        "## 3. Standards",
        "## 4. Rules",
        "## 5. AI use",
        "## 6. Safety gates",
        "## 7. CRS",
        "## 8. Retractions and known gaps",
    ):
        assert heading in md
    assert run_id in md


def test_a_figure_that_was_not_recorded_reads_not_recorded_never_zero(world, audit_dir):
    run_id = _review(world)
    with connect() as conn:
        conn.execute("DELETE FROM page_ledger WHERE document_id = ?", (world["sub"],))
    audit = review_audit.build(run_id, _scope(world))
    assert audit["pages"]["total"] is None
    md = review_audit.render_markdown(audit)
    assert "pages in the document: not recorded" in md
    assert "pages in the document: 0" not in md


def test_a_failed_ai_step_is_listed_failed_and_the_verdicts_do_not_change(
    world, audit_dir
):
    run_id = _review(world)
    before = review_audit.build(run_id, _scope(world))
    failed = json.dumps(
        {
            "ran": False,
            "complete": False,
            "calls_made": 1,
            "reason": "timeout",
            "model": "invented-model",
        }
    )
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ? WHERE id = ?", (failed, run_id)
        )
    after = review_audit.build(run_id, _scope(world))
    step = next(
        s for s in after["ai_use"]["steps"] if s["name"] == "ai_engineering_check"
    )
    assert step["state"] == "failed" and step["reason"] == "timeout"
    assert step["model"] == "invented-model" and step["calls"] == 1
    assert "no verdict is more confident" in step["effect_on_verdicts"]
    assert after["rules"]["verdict_counts"] == before["rules"]["verdict_counts"]
    assert after["rules"]["rows"] == before["rules"]["rows"]


def test_a_step_with_no_status_is_not_recorded_not_failed(world, audit_dir):
    run_id = _review(world)
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = NULL WHERE id = ?", (run_id,)
        )
    step = review_audit.build(run_id, _scope(world))["ai_use"]["steps"][0]
    assert step["state"] == "not recorded" and step["calls"] is None


def test_a_failure_writing_the_audit_never_breaks_the_review(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(review_audit, "render_markdown", boom)
    run_id = _review(world)  # review_jobs.run still returns "done"
    row = (
        connect()
        .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["status"] == "completed"
    assert _files(audit_dir) == []


def test_the_audit_holds_no_page_text_beyond_stored_quotes(world, audit_dir):
    run_id = _review(world)
    md = review_audit.render_markdown(review_audit.build(run_id, _scope(world)))
    assert "Pump shall comply with API 610" not in md
    assert "Equipment noise level shall not exceed" not in md
