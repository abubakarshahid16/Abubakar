"""Persistent workflow records for AI-assisted engineering reviews.

Analysis remains evidence-first and read-only. A review finding is the
workflow record created from that evidence and then managed by people.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_schema() -> None:
    conn = connect()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_findings (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                baseline_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                requirement TEXT NOT NULL,
                finding TEXT NOT NULL,
                required_action TEXT NOT NULL,
                response_text TEXT,
                disposition TEXT,
                citation_ids TEXT NOT NULL DEFAULT '[]',
                owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                approval_status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                escalation_level INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)")}
        for name, definition in {
            "response_text": "TEXT",
            "disposition": "TEXT",
            "approved_by": "TEXT",
            "approved_at": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE review_findings ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_document "
                     "ON review_findings(document_id, status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_due "
                     "ON review_findings(due_date, status)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS review_finding_events (
                id TEXT PRIMARY KEY,
                finding_id TEXT NOT NULL REFERENCES review_findings(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                changes TEXT NOT NULL DEFAULT '{}',
                actor_user_id TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_finding_events_finding "
                     "ON review_finding_events(finding_id, created_at DESC)")


def _row(row) -> dict:
    result = dict(row)
    try:
        result["citation_ids"] = json.loads(result.get("citation_ids") or "[]")
    except (TypeError, ValueError):
        result["citation_ids"] = []
    return result


def _event(conn, finding_id: str, event_type: str, changes: dict,
           actor_user_id: str | None, created_at: str) -> None:
    conn.execute(
        """INSERT INTO review_finding_events
           (id, finding_id, event_type, changes, actor_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), finding_id, event_type, json.dumps(changes),
         actor_user_id, created_at),
    )


def create(payload: dict, *, created_by: str | None) -> dict:
    ensure_schema()
    now = _now()
    finding_id = str(uuid.uuid4())
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO review_findings
               (id, document_id, baseline_document_id, category, severity,
               requirement, finding, required_action, response_text, disposition, citation_ids,
               owner_user_id, due_date, status, approval_status, approved_by, approved_at,
               escalation_level, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding_id, payload["document_id"], payload.get("baseline_document_id"),
                payload["category"], payload["severity"], payload["requirement"],
                payload["finding"], payload["required_action"],
                payload.get("response_text"), payload.get("disposition"),
                json.dumps(payload.get("citation_ids", [])), payload.get("owner_user_id"),
                payload.get("due_date"), payload.get("status", "open"),
                payload.get("approval_status", "pending"), payload.get("approved_by"),
                payload.get("approved_at"), payload.get("escalation_level", 0),
                created_by, now, now,
            ),
        )
        _event(conn, finding_id, "created", {
            "severity": payload["severity"],
            "status": payload.get("status", "open"),
            "approval_status": payload.get("approval_status", "pending"),
        }, created_by, now)
    return get(finding_id)  # type: ignore[return-value]


def get(finding_id: str) -> dict | None:
    ensure_schema()
    row = connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    return _row(row) if row else None


def list_findings(*, document_id: str | None = None, status: str | None = None,
                  allowed_document_ids: frozenset[str] | None = None) -> list[dict]:
    ensure_schema()
    clauses: list[str] = []
    args: list[str] = []
    if document_id:
        clauses.append("document_id = ?")
        args.append(document_id)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if allowed_document_ids is not None:
        if not allowed_document_ids:
            return []
        marks = ",".join("?" for _ in allowed_document_ids)
        clauses.append(f"document_id IN ({marks})")
        args.extend(sorted(allowed_document_ids))
    sql = "SELECT * FROM review_findings"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += (" ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 "
            "WHEN 'minor' THEN 2 ELSE 3 END, updated_at DESC")
    return [_row(row) for row in connect().execute(sql, args).fetchall()]


def history(finding_id: str) -> list[dict]:
    ensure_schema()
    rows = connect().execute(
        "SELECT * FROM review_finding_events WHERE finding_id = ? "
        "ORDER BY rowid ASC", (finding_id,)
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["changes"] = json.loads(item.get("changes") or "{}")
        except (TypeError, ValueError):
            item["changes"] = {}
        out.append(item)
    return out


def update(finding_id: str, changes: dict, *, actor_user_id: str | None = None) -> dict | None:
    ensure_schema()
    allowed = {"owner_user_id", "due_date", "status", "approval_status",
               "escalation_level", "required_action", "severity", "response_text",
               "disposition", "approved_by", "approved_at"}
    current = get(finding_id)
    if current is None:
        return None
    changed = {key: value for key, value in changes.items()
               if key in allowed and value is not None
               and value != current.get(key)}
    if not changed:
        return current
    sets: list[str] = []
    args: list[object] = []
    for key, value in changed.items():
        sets.append(f"{key} = ?")
        args.append(value)
    now = _now()
    sets.append("updated_at = ?")
    args.extend([now, finding_id])
    conn = connect()
    with conn:
        if conn.execute(f"UPDATE review_findings SET {', '.join(sets)} WHERE id = ?", args).rowcount == 0:
            return None
        _event(conn, finding_id, "updated", changed, actor_user_id, now)
    return get(finding_id)
