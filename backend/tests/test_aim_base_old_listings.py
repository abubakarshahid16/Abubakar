"""Order 14 base branch: a general review run changes no old listing.

A general run (`app.aim_review`) is a `review_runs` row like any other. Every old reader that takes "not an AI run" to mean "a rule
check" (the paper's latest rule-check run, the run list, the latest cancelled run, the latest run's standards, the export status,
the findings' latest run) must not see it: `aim_review_store.exclude`. Each reader is asked before and after a NEWER general run
(completed, then cancelled) is added; every answer must stay the same. Invented ids only.
"""

from __future__ import annotations

import pytest

from app import (
    aim_review_store,
    crs_completeness,
    db,
    export_status,
    finding_query,
    form_reader_run,
    review_engine,
    review_leaving,
    review_points_service,
    submittal_review,
)
from tests.test_p3_review_jobs import _doc, temp_storage  # noqa: F401 - fixture

PAPER = "doc_inv_paper"
BOOK = "doc_inv_book"


def _run(
    run_id: str, status: str, started: str, *, scope_book: str | None = None
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, PAPER, status, started, started, started),
        )
        if scope_book:
            conn.execute(
                "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, selection_reason,"
                " selection_method, included, created_at) VALUES (?, ?, ?, 'x', 'scope', 1, 't')",
                (f"as_{run_id}", run_id, scope_book),
            )


def _general(run_id: str, status: str, started: str) -> None:
    """A general review run as the job queue makes it: the `review_runs` row and its `aim_runs` row."""
    _run(run_id, status, started)
    with db.connect() as conn:
        aim_review_store.start_run(conn, run_id, PAPER, started)


def _listings() -> dict:
    conn = db.connect()
    scope = frozenset({PAPER, BOOK})
    return {
        "runs_of_paper": review_points_service.runs_of_paper(conn, PAPER),
        "last_rule_check_run": review_leaving.last_rule_check_run(conn, PAPER),
        "latest_cancelled": crs_completeness.latest_cancelled(PAPER),
        "run_list": [
            r["id"]
            for r in submittal_review.list_review_runs(allowed_document_ids=scope)
        ],
        "run_list_of_paper": [
            r["id"]
            for r in submittal_review.list_review_runs(
                allowed_document_ids=scope, submittal_document_id=PAPER
            )
        ],
        "standards_of": form_reader_run.standards_of(PAPER),
        "export_latest": (export_status.latest_run(PAPER) or {}).get("id"),
        "finding_latest": finding_query.latest_run_ids(None).get(PAPER),
        "finding_latest_scoped": finding_query.latest_run_ids(scope).get(PAPER),
        "earlier_books": [
            b.get("id") for b in review_engine._earlier_books(conn, PAPER)
        ],
    }


@pytest.fixture
def paper(temp_storage):  # noqa: F811
    _doc(PAPER, "CONTRACTOR_SUBMITTAL", "invented paper text")
    _doc(BOOK, "COMPANY_STANDARD", "invented rule book text")
    aim_review_store.ensure_schema()
    _run("rc_old", "completed", "2026-11-01T10:00:00Z", scope_book=BOOK)
    _run("rc_older_complete", "complete", "2026-10-01T10:00:00Z", scope_book=BOOK)


def test_the_old_listings_see_the_rule_check_before_any_general_run(paper):
    """The precondition: each reader really answers with the old run, so "unchanged" below is not "None == None"."""
    got = _listings()
    assert got["runs_of_paper"][0] == "rc_old"
    assert got["last_rule_check_run"] == "rc_old"
    assert got["latest_cancelled"] is None
    assert "rc_old" in got["run_list"] and got["run_list_of_paper"][0] == "rc_old"
    assert got["standards_of"] == [BOOK]
    assert got["export_latest"] == "rc_old"
    assert got["finding_latest"] == got["finding_latest_scoped"] == "rc_old"


@pytest.mark.parametrize("status", ["completed", "cancelled", "running"])
def test_a_newer_general_run_changes_no_old_listing(paper, status):
    before = _listings()
    _general("gen_new", status, "2026-11-18T10:00:00Z")
    after = _listings()
    assert after == before
    assert aim_review_store.is_general(db.connect(), "gen_new")
    assert not aim_review_store.is_general(db.connect(), "rc_old")


def test_without_the_table_the_readers_work_as_before(temp_storage):  # noqa: F811
    """A database made before the general review (no `aim_runs`): `exclude` adds nothing, nothing fails."""
    conn = db.connect()
    assert not aim_review_store.has_tables(conn)
    assert aim_review_store.exclude(conn) == ""
    assert review_points_service.runs_of_paper(conn, PAPER) == (None, None)
    assert review_leaving.last_rule_check_run(conn, PAPER) is None


def test_exclude_names_the_alias_it_is_given(temp_storage):  # noqa: F811
    aim_review_store.ensure_schema()
    conn = db.connect()
    assert aim_review_store.exclude(conn) == " AND " + aim_review_store.EXCLUDE_SQL
    assert (
        aim_review_store.exclude(conn, "x")
        == " AND x.id NOT IN (SELECT run_id FROM aim_runs)"
    )
