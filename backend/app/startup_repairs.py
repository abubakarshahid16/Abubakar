"""Idempotent repairs for retained content and legacy history, before workers start."""
from __future__ import annotations

import json
import uuid

from . import job_queue, orphan_guard, states


def restore_blocked_refresh(conn, document_id: str) -> bool:
    """Retain a complete previous index when the reference guard refused its replacement."""
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None or not str(row["error_message"] or "").startswith(orphan_guard._BLOCKED["re_chunk"]):
        return False
    page_count = int(row["page_count"] or 0)
    pages_done = int(row["pages_done"] or 0)
    chunk_count = int(row["chunk_count"] or 0)
    embedded_count = int(row["embedded_count"] or 0)
    complete = page_count > 0 and pages_done == page_count and chunk_count > 0
    pages = conn.execute("SELECT COUNT(*) FROM pages WHERE document_id = ?", (document_id,)).fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)).fetchone()[0]
    if not complete or pages < page_count or chunks < chunk_count:
        return False
    status = states.READY if embedded_count >= chunk_count else states.PARTIALLY_SEARCHABLE
    conn.execute("UPDATE documents SET status = ?, error_code = 'update_refused', claimed_by = NULL, claimed_at = NULL WHERE id = ?", (status, document_id))
    conn.execute(
        "UPDATE jobs SET state = 'cancelled', claimed_by = NULL, claimed_at = NULL, updated_at = ? "
        "WHERE document_id = ? AND stage = 'chunk' AND state IN ('queued', 'running', 'retrying', 'poisoned')",
        (job_queue.now_iso(), document_id),
    )
    return True


def candidates(conn) -> dict:
    return {
        "actors": conn.execute("SELECT COUNT(*) FROM audit_events WHERE actor_user_id IS NOT NULL AND actor_user_id NOT IN (SELECT id FROM users)").fetchone()[0],
        "documents": conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'failed' AND error_message LIKE ?", (orphan_guard._BLOCKED["re_chunk"] + "%",)).fetchone()[0],
        "reviews": conn.execute(
            "SELECT COUNT(*) FROM review_runs r WHERE r.status = 'pending' AND r.updated_at < ? "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.review_run_id = r.id AND j.state IN ('queued', 'running', 'retrying'))",
            (job_queue.stale_cutoff(),),
        ).fetchone()[0],
    }


def repair(conn) -> dict:
    counts = {"actors": 0, "documents": 0, "reviews": 0}
    with conn:
        rows = conn.execute("SELECT id, actor_user_id, detail FROM audit_events WHERE actor_user_id IS NOT NULL AND actor_user_id NOT IN (SELECT id FROM users)").fetchall()
        for row in rows:
            try:
                detail = json.loads(row["detail"] or "{}")
            except (ValueError, TypeError):
                detail = {"previous_detail": row["detail"]}
            if not isinstance(detail, dict):
                detail = {"previous_detail": detail}
            detail["unresolved_actor_user_id"] = row["actor_user_id"]
            counts["actors"] += conn.execute(
                "UPDATE audit_events SET actor_user_id = NULL, detail = ? WHERE id = ? AND actor_user_id = ?",
                (json.dumps(detail), row["id"], row["actor_user_id"]),
            ).rowcount
        rows = conn.execute("SELECT id FROM documents WHERE status = 'failed'").fetchall()
        for row in rows:
            counts["documents"] += int(restore_blocked_refresh(conn, row["id"]))
        counts["reviews"] = conn.execute(
            "UPDATE review_runs SET status = 'cancelled', updated_at = ?, outcome_json = ? "
            "WHERE status = 'pending' AND updated_at < ? AND NOT EXISTS "
            "(SELECT 1 FROM jobs j WHERE j.review_run_id = review_runs.id AND j.state IN ('queued', 'running', 'retrying'))",
            (job_queue.now_iso(), json.dumps({"error": "Interrupted review has no queued or running job; start a new review to retry."}), job_queue.stale_cutoff()),
        ).rowcount
        if any(counts.values()):
            conn.execute(
                "INSERT INTO audit_events (id, at, actor_user_id, actor_username, action, resource_type, resource_id, detail, outcome) VALUES (?, ?, NULL, 'System', 'system.history_repaired', 'database', NULL, ?, 'ok')",
                (f"audit_{uuid.uuid4().hex}", job_queue.now_iso(), json.dumps(counts)),
            )
    return counts


def at_startup() -> dict:
    from . import live_guard
    from .config import settings
    from .db import connect

    conn = connect()
    if not any(candidates(conn).values()):
        return {"actors": 0, "documents": 0, "reviews": 0}
    if live_guard.is_live_shaped(settings.db_path):
        live_guard.verified_rollback_point(settings.db_path)
    return repair(conn)
