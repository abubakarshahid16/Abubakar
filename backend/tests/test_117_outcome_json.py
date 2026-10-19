"""Order 117 item 4: a run's outcome lives in `outcome_json`, not `refusal_reason`.

The column held every run's outcome - the recommended code on a completed run,
the error on a failed one - under a name that only fit failures. It moved:
writers write `outcome_json`, readers read it, and a database made before the
move has each run's outcome copied across when the schema is ensured.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import comparison, db, submittal_review
from app.config import settings

_OLD_REVIEW_RUNS = """CREATE TABLE review_runs (
    id TEXT PRIMARY KEY,
    submittal_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    template_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    refusal_reason TEXT,
    model_name TEXT,
    config_version TEXT,
    started_by TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "outcome.sqlite")
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES ('doc_sub','s.pdf','sha',1,'s.pdf',"
            "'ready',1,'2026-10-18T00:00:00Z')"
        )
    yield
    db.reset_connection()


def _columns() -> set[str]:
    return {r[1] for r in db.connect().execute("PRAGMA table_info(review_runs)")}


def test_a_database_made_before_the_move_gets_each_outcome_copied_across():
    stored = {"recommended_code": "Code 2", "reason": "two findings need the engineer"}
    with db.connect() as conn:
        conn.execute(_OLD_REVIEW_RUNS)
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
            "created_at,updated_at) VALUES ('run_old','doc_sub','completed',?,"
            "'2026-10-01T00:00:00Z','2026-10-01T00:00:00Z')",
            (json.dumps(stored),),
        )
    assert "outcome_json" not in _columns()

    submittal_review.ensure_schema()

    assert "outcome_json" in _columns()
    assert (
        comparison.run_outcome("run_old", allowed_document_ids=frozenset({"doc_sub"}))
        == stored
    )


def test_ensuring_a_current_schema_writes_nothing_so_a_read_path_stays_read_only():
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,"
            "created_at,updated_at) VALUES ('run_new','doc_sub','failed',"
            "'{\"error\": \"current\"}','2026-10-18T00:00:00Z','2026-10-18T00:00:00Z')"
        )
    conn = db.connect()
    writes = (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)

    def deny_writes(action, table, _arg2, dbname, _source):
        # SQLite's own bookkeeping (sqlite_*, temp) is not a write to the data.
        if (
            action in writes
            and dbname != "temp"
            and not str(table).startswith("sqlite_")
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_writes)
    try:
        submittal_review.ensure_schema.__wrapped__()  # as a GET's first call would
    finally:
        conn.set_authorizer(None)

    row = conn.execute(
        "SELECT outcome_json FROM review_runs WHERE id = 'run_new'"
    ).fetchone()
    assert json.loads(row["outcome_json"]) == {"error": "current"}


def test_a_writer_fills_outcome_json_and_leaves_the_old_column_alone():
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES ('run_dead','doc_sub','running','2026-10-18T00:00:00Z',"
            "'2026-10-18T00:00:00Z')"
        )

    assert submittal_review.fail_orphaned_review_runs() == 1

    row = (
        db.connect()
        .execute(
            "SELECT refusal_reason, outcome_json FROM review_runs WHERE id = 'run_dead'"
        )
        .fetchone()
    )
    assert row["refusal_reason"] is None
    assert json.loads(row["outcome_json"]) == {
        "error": submittal_review.ORPHANED_RUN_REASON
    }


def test_the_copy_never_overwrites_an_outcome_written_after_the_column_was_added(
    monkeypatch,
):
    """cloud's #1137 review: the ALTER commits at once, so a writer can store a
    newer outcome before the copy runs. The copy must leave that one alone."""
    with db.connect() as conn:
        conn.execute(_OLD_REVIEW_RUNS)
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
            "created_at,updated_at) VALUES ('run_race','doc_sub','failed',NULL,"
            "'2026-10-18T00:00:00Z','2026-10-18T00:00:00Z')"
        )
    real_add = submittal_review.add_column_if_missing

    def add_then_a_writer_lands(conn, table, column, definition):
        added = real_add(conn, table, column, definition)
        if added and column == "outcome_json":
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = 'run_race'",
                (json.dumps({"error": "newer"}),),
            )
        return added

    monkeypatch.setattr(
        submittal_review, "add_column_if_missing", add_then_a_writer_lands
    )

    submittal_review.ensure_schema()

    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = 'run_race'")
        .fetchone()
    )
    assert json.loads(row["outcome_json"]) == {"error": "newer"}
