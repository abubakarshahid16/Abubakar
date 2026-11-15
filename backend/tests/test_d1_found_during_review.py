"""The points listing says how many rule books the paper's review found only while it ran and did not send (D1)."""

from __future__ import annotations

import json

from app import claude_auto_approve, db, review_points_service, submittal_review

NOW = "2026-11-15T00:00:00Z"


def _run(run_id, outcome):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('p','p.pdf','aa',1,'p.pdf','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, outcome_json) VALUES (?, 'p', 'completed', ?, ?, ?)",
            (run_id, NOW, NOW, json.dumps(outcome)),
        )


def test_the_listing_count_is_the_largest_found_during_review_of_the_papers_runs(
    tmp_path, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "f.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    _run(
        "a", {claude_auto_approve.SHOWN_KEY: {"not_sent": 3, "found_during_review": 2}}
    )
    _run(
        "b", {claude_auto_approve.SHOWN_KEY: {"not_sent": 1, "found_during_review": 1}}
    )
    _run("c", {})
    conn = db.connect()
    assert review_points_service._found_during_review(conn, "a", "b") == 2
    assert review_points_service._found_during_review(conn, "c", None) == 0
    assert review_points_service._found_during_review(conn, None, None) == 0
    db.reset_connection()
