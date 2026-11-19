"""Technical-query records and the first safe import slice.

This module stores an imported message and its attachment metadata; it does not
connect to a mailbox or send email. Provider adapters and document ingestion
remain separate stages so untrusted messages cannot trigger actions.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import connect

STATUSES = (
    "received",
    "triage",
    "drafting",
    "awaiting_review",
    "changes_requested",
    "approved",
    "send_pending",
    "sent",
    "awaiting_confirmation",
    "resolved",
    "duplicate",
    "cancelled",
    "failed",
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_schema() -> None:
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS technical_queries (
            id TEXT PRIMARY KEY, owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            contractor_name TEXT, department TEXT, subject TEXT NOT NULL, extracted_question TEXT,
            status TEXT NOT NULL CHECK(status IN ('received','triage','drafting','awaiting_review','changes_requested','approved','send_pending','sent','awaiting_confirmation','resolved','duplicate','cancelled','failed')),
            priority TEXT NOT NULL DEFAULT 'normal', received_at TEXT NOT NULL, due_at TEXT,
            resolved_at TEXT, resolution_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tq_owner_status ON technical_queries(owner_user_id, status, updated_at DESC);
        CREATE TABLE IF NOT EXISTS query_messages (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            provider TEXT NOT NULL, mailbox_id TEXT, provider_message_id TEXT NOT NULL,
            provider_thread_id TEXT, internet_message_id TEXT, from_address TEXT NOT NULL,
            to_addresses TEXT NOT NULL, cc_addresses TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
            sent_at TEXT, received_at TEXT NOT NULL, raw_message_hash TEXT, is_inbound INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, UNIQUE(provider, mailbox_id, provider_message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_messages_thread ON query_messages(provider, mailbox_id, provider_thread_id);
        CREATE TABLE IF NOT EXISTS query_attachments (
            id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES query_messages(id) ON DELETE CASCADE,
            filename TEXT NOT NULL, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT,
            storage_ref TEXT, scan_status TEXT NOT NULL DEFAULT 'pending', parse_status TEXT NOT NULL DEFAULT 'pending',
            document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS query_drafts (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            version INTEGER NOT NULL, answer TEXT NOT NULL, assumptions_json TEXT NOT NULL DEFAULT '[]',
            unresolved_json TEXT NOT NULL DEFAULT '[]', model TEXT, prompt_version TEXT,
            created_by TEXT REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL,
            UNIQUE(query_id, version)
        );
        CREATE TABLE IF NOT EXISTS query_decisions (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            draft_id TEXT REFERENCES query_drafts(id) ON DELETE SET NULL, actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            decision TEXT NOT NULL CHECK(decision IN ('request_changes','approve','reject','close')),
            comment TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS query_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL, event TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
        );
        """)


def _event(
    conn, query_id: str, event: str, actor: str | None, detail: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO query_events(query_id, actor_user_id, event, detail, created_at) VALUES (?,?,?,?,?)",
        (query_id, actor, event, detail, now()),
    )


def _visible_where(
    user_id: str | None, is_admin: bool, unrestricted: bool
) -> tuple[str, list[Any]]:
    if unrestricted or is_admin:
        return "", []
    if user_id is None:
        return " WHERE 1 = 0", []
    return " WHERE owner_user_id = ?", [user_id]


def import_message(
    data: dict[str, Any],
    actor_user_id: str | None,
    is_admin: bool = False,
    unrestricted: bool = False,
) -> tuple[dict[str, Any], bool]:
    received = data.get("received_at") or now()
    qid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    with connect() as conn:
        existing = conn.execute(
            "SELECT query_id FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_message_id=?",
            (data["provider"], data.get("mailbox_id"), data["provider_message_id"]),
        ).fetchone()
        if existing:
            visible = get(existing["query_id"], actor_user_id, is_admin, unrestricted)
            if visible is None:
                raise PermissionError("technical query is not visible to this user")
            return visible, True
        conn.execute(
            "INSERT INTO technical_queries(id,owner_user_id,contractor_name,department,subject,extracted_question,status,priority,received_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                qid,
                actor_user_id,
                data.get("contractor_name"),
                data.get("department"),
                data["subject"],
                data.get("question"),
                "received",
                data.get("priority", "normal"),
                received,
                now(),
                now(),
            ),
        )
        conn.execute(
            "INSERT INTO query_messages(id,query_id,provider,mailbox_id,provider_message_id,provider_thread_id,internet_message_id,from_address,to_addresses,cc_addresses,subject,body,sent_at,received_at,raw_message_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                qid,
                data["provider"],
                data.get("mailbox_id"),
                data["provider_message_id"],
                data.get("provider_thread_id"),
                data.get("internet_message_id"),
                data["from_address"],
                json.dumps(data.get("to_addresses", [])),
                json.dumps(data.get("cc_addresses", [])),
                data["subject"],
                data["body"],
                data.get("sent_at"),
                received,
                data.get("raw_message_hash"),
                now(),
            ),
        )
        for attachment in data.get("attachments", []):
            conn.execute(
                "INSERT INTO query_attachments(id,message_id,filename,media_type,size_bytes,sha256,storage_ref,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    mid,
                    attachment["filename"],
                    attachment["media_type"],
                    attachment["size_bytes"],
                    attachment.get("sha256"),
                    attachment.get("storage_ref"),
                    now(),
                ),
            )
        _event(conn, qid, "received", actor_user_id, "provider message imported")
    return get(qid, actor_user_id, is_admin, unrestricted) or {}, False


def list_queries(
    user_id: str | None, is_admin: bool, unrestricted: bool, status: str | None = None
) -> list[dict[str, Any]]:
    where, args = _visible_where(user_id, is_admin, unrestricted)
    if status:
        where += " AND " if where else " WHERE "
        where += "status = ?"
        args.append(status)
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM technical_queries" + where + " ORDER BY updated_at DESC",
                args,
            ).fetchall()
        ]


def get(
    query_id: str, user_id: str | None, is_admin: bool, unrestricted: bool
) -> dict[str, Any] | None:
    where, args = _visible_where(user_id, is_admin, unrestricted)
    where += " AND " if where else " WHERE "
    where += "id = ?"
    args.append(query_id)
    with connect() as conn:
        row = conn.execute("SELECT * FROM technical_queries" + where, args).fetchone()
        if not row:
            return None
        result = dict(row)
        result["messages"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_messages WHERE query_id=? ORDER BY received_at",
                (query_id,),
            )
        ]
        for message in result["messages"]:
            message["to_addresses"], message["cc_addresses"] = (
                json.loads(message["to_addresses"] or "[]"),
                json.loads(message["cc_addresses"] or "[]"),
            )
            message["attachments"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM query_attachments WHERE message_id=?",
                    (message["id"],),
                )
            ]
        result["drafts"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_drafts WHERE query_id=? ORDER BY version",
                (query_id,),
            )
        ]
        result["decisions"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_decisions WHERE query_id=? ORDER BY created_at",
                (query_id,),
            )
        ]
        result["events"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_events WHERE query_id=? ORDER BY id", (query_id,)
            )
        ]
        return result


def add_draft(
    query_id: str,
    answer: str,
    assumptions: list[str],
    unresolved: list[str],
    actor_user_id: str | None,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    with connect() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS v FROM query_drafts WHERE query_id=?",
            (query_id,),
        ).fetchone()["v"]
        did = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO query_drafts(id,query_id,version,answer,assumptions_json,unresolved_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                did,
                query_id,
                version,
                answer,
                json.dumps(assumptions),
                json.dumps(unresolved),
                actor_user_id,
                now(),
            ),
        )
        conn.execute(
            "UPDATE technical_queries SET status='awaiting_review',updated_at=? WHERE id=?",
            (now(), query_id),
        )
        _event(
            conn,
            query_id,
            "draft_created",
            actor_user_id,
            f"draft={did};version={version}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def link_attachment(
    query_id: str,
    attachment_id: str,
    document_id: str,
    actor_user_id: str | None,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM query_attachments WHERE id=? AND message_id IN "
            "(SELECT id FROM query_messages WHERE query_id=?)",
            (attachment_id, query_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE query_attachments SET document_id=?, scan_status='accepted', parse_status='pending' WHERE id=?",
            (document_id, attachment_id),
        )
        _event(
            conn,
            query_id,
            "attachment_linked",
            actor_user_id,
            f"attachment={attachment_id};document={document_id}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def decide(
    query_id: str,
    decision: str,
    actor_user_id: str | None,
    comment: str | None,
    draft_id: str | None,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if decision not in {"request_changes", "approve", "reject", "close"}:
        raise ValueError("unknown technical-query decision")
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    target = {
        "request_changes": "changes_requested",
        "approve": "approved",
        "reject": "failed",
        "close": "resolved",
    }[decision]
    with connect() as conn:
        conn.execute(
            "INSERT INTO query_decisions(id,query_id,draft_id,actor_user_id,decision,comment,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                query_id,
                draft_id,
                actor_user_id,
                decision,
                comment,
                now(),
            ),
        )
        conn.execute(
            "UPDATE technical_queries SET status=?,resolved_at=?,resolution_reason=?,updated_at=? WHERE id=?",
            (
                target,
                now() if target == "resolved" else None,
                comment if target == "resolved" else None,
                now(),
                query_id,
            ),
        )
        _event(conn, query_id, "decision", actor_user_id, f"decision={decision}")
    return get(query_id, user_id, is_admin, unrestricted)
