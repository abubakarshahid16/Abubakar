"""Order 109: the review runs list answers in seconds.

`GET /api/reviews/runs` took 17-36 s for 57 runs: per run it scanned every job
(no index), read the run row three more times, and computed the same values
twice. These tests pin the MECHANISM (indexes present and used, no repeated
run reads, one grouped count), never a wall-clock time, and that the values
returned are unchanged. Invented runs and findings only.
"""

from __future__ import annotations

import json

from app import ai_engineering_check, comparison, crs_issue, db, review_jobs
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)


def _indexes() -> set[str]:
    return {
        r["name"]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }


def _plan(sql: str, args: tuple) -> str:
    return "; ".join(
        r[3] for r in db.connect().execute("EXPLAIN QUERY PLAN " + sql, args)
    )


def _listed(client) -> list[dict]:
    r = client.get("/api/reviews/runs")
    assert r.status_code == 200, r.text
    return r.json()["runs"]


def test_the_list_lookups_have_their_indexes():
    names = _indexes()
    assert {
        "idx_jobs_review_run",
        "idx_review_runs_created",
        "idx_review_findings_run_tag",
    } <= names


def test_the_newest_job_of_a_run_is_found_by_index_not_by_scanning_every_job():
    plan = _plan(
        "SELECT id FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        ("r",),
    )
    assert "idx_jobs_review_run" in plan and "SCAN jobs" not in plan, plan


def test_the_issued_copies_index_is_added_where_the_table_exists_and_nowhere_else():
    assert not crs_issue._has("crs_issued_copies")
    crs_issue.ensure_indexes()  # startup on a database that never issued
    assert not crs_issue._has("crs_issued_copies"), "startup must create no table"
    crs_issue.ensure_schema()
    assert "idx_crs_issued_copies_run" in _indexes()
    plan = _plan(
        "SELECT MAX(issued_at) FROM crs_issued_copies WHERE review_run_id = ?", ("r",)
    )
    assert "idx_crs_issued_copies_run" in plan, plan


def test_the_list_reads_each_run_row_once_not_once_per_field(monkeypatch):
    from app import submittal_review

    doc = _submittal()
    runs = [_run(doc) for _ in range(3)]
    for run_id in runs:
        _finding(doc, run_id, "NON_COMPLIANT")
    client = _client(doc)
    calls: list[str] = []
    real = submittal_review.get_review_run

    def spy(run_id, **kwargs):
        calls.append(run_id)
        return real(run_id, **kwargs)

    monkeypatch.setattr(submittal_review, "get_review_run", spy)
    assert len(_listed(client)) == 3
    assert calls == [], f"the list re-read {len(calls)} run rows it already held"


def test_one_grouped_count_per_run_gives_total_and_statuses():
    """In the request's own thread (the route runs on another connection)."""
    from app import access, main, submittal_review

    doc = _submittal()
    for _ in range(3):
        _finding(doc, _run(doc), "NON_COMPLIANT")
    allowed = frozenset({doc})
    scope = access.AccessScope(user_id="eng", allowed_document_ids=allowed)
    rows = submittal_review.list_review_runs(allowed_document_ids=allowed)
    seen: list[str] = []
    db.connect().set_trace_callback(seen.append)
    try:
        summaries = [main._run_summary(run, scope) for run in rows]
    finally:
        db.connect().set_trace_callback(None)
    assert [s["findings_total"] for s in summaries] == [1, 1, 1]
    counts = [s for s in seen if "FROM review_findings" in s and "COUNT(" in s]
    assert len(counts) == 3, counts


def test_the_counts_are_unchanged_by_the_grouped_query():
    doc = _submittal()
    run_id = _run(doc)
    for status in ("NON_COMPLIANT", "NON_COMPLIANT", "COMPLIANT", None):
        _finding(doc, run_id, status, equipment_tag="SYN-V-0001")
    _finding(doc, run_id, "UNCLEAR", equipment_tag=None)
    row = next(r for r in _listed(_client(doc)) if r["review_run_id"] == run_id)
    assert row["findings_total"] == 5  # the null-status finding still counts
    assert row["by_status"] == {"COMPLIANT": 1, "NON_COMPLIANT": 2, "UNCLEAR": 1}
    assert row["equipment_tags"] == ["SYN-V-0001"]


def test_a_handed_in_run_gives_the_same_answer_as_reading_it():
    doc = _submittal()
    run_id = _run(doc)
    status = {"state": "complete", "kept": 2}
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ? WHERE id = ?",
            (json.dumps(status), run_id),
        )
    allowed = frozenset({doc})
    from app import submittal_review

    run = submittal_review.get_review_run(run_id, allowed_document_ids=allowed)
    assert comparison.run_outcome(
        run_id, allowed_document_ids=allowed, run=run
    ) == comparison.run_outcome(run_id, allowed_document_ids=allowed)
    assert (
        ai_engineering_check.ai_check_status(
            run_id, allowed_document_ids=allowed, run=run
        )
        == status
    )


def test_a_handed_in_row_for_another_run_is_not_trusted():
    doc = _submittal()
    first, second = _run(doc, "Approved"), _run(doc, "Revise and Resubmit")
    allowed = frozenset({doc})
    from app import submittal_review

    other = submittal_review.get_review_run(first, allowed_document_ids=allowed)
    assert (
        comparison.run_outcome(second, allowed_document_ids=allowed, run=other)[
            "recommended_code"
        ]
        == "Revise and Resubmit"
    )
    # and a run the caller may not read stays unreadable whatever is handed in
    assert (
        comparison.run_outcome(second, allowed_document_ids=frozenset(), run=other)
        is None
    )


def test_the_job_shown_is_still_the_newest_one():
    doc = _submittal()
    run_id = _run(doc)
    with db.connect() as conn:
        for job_id, started in (
            ("j-old", "2026-01-01T00:00:00"),
            ("j-new", "2026-02-01T00:00:00"),
        ):
            conn.execute(
                "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,"
                " review_run_id) VALUES (?, ?, 'review', 'done', ?, ?, ?)",
                (job_id, doc, started, NOW, run_id),
            )
    assert review_jobs.job_for_run(run_id)["id"] == "j-new"
    row = next(r for r in _listed(_client(doc)) if r["review_run_id"] == run_id)
    assert row["job"]["id"] == "j-new"
