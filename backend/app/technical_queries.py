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
            assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
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
            sent_at TEXT, received_at TEXT NOT NULL, raw_message_hash TEXT, raw_storage_ref TEXT, is_inbound INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, UNIQUE(provider, mailbox_id, provider_message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_query_messages_thread ON query_messages(provider, mailbox_id, provider_thread_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_query_messages_identity ON query_messages(provider, COALESCE(mailbox_id, ''), provider_message_id);
        CREATE TABLE IF NOT EXISTS query_attachments (
            id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES query_messages(id) ON DELETE CASCADE,
            filename TEXT NOT NULL, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT,
            storage_ref TEXT, scan_status TEXT NOT NULL DEFAULT 'pending', parse_status TEXT NOT NULL DEFAULT 'pending',
            document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS query_drafts (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            version INTEGER NOT NULL, answer TEXT NOT NULL, assumptions_json TEXT NOT NULL DEFAULT '[]',
            unresolved_json TEXT NOT NULL DEFAULT '[]', citations_json TEXT NOT NULL DEFAULT '[]',
            model TEXT, prompt_version TEXT,
            created_by TEXT REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL,
            UNIQUE(query_id, version)
        );
        CREATE TABLE IF NOT EXISTS query_evidence (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
            page_start INTEGER, page_end INTEGER, locator TEXT, exact_quote TEXT NOT NULL,
            quote_hash TEXT NOT NULL, evidence_state TEXT NOT NULL DEFAULT 'verified',
            conflict_group TEXT, supersession_state TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_query_evidence_query ON query_evidence(query_id);
        CREATE TABLE IF NOT EXISTS query_decisions (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            draft_id TEXT REFERENCES query_drafts(id) ON DELETE SET NULL, actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            decision TEXT NOT NULL CHECK(decision IN ('request_changes','approve','reject','close')),
            comment TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS query_sends (
            id TEXT PRIMARY KEY, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            draft_id TEXT REFERENCES query_drafts(id) ON DELETE SET NULL, idempotency_key TEXT NOT NULL UNIQUE,
            to_addresses TEXT NOT NULL, cc_addresses TEXT NOT NULL, state TEXT NOT NULL,
            provider_message_id TEXT, error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gmail_oauth_states (
            state TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL, used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS gmail_mailboxes (
            id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email TEXT NOT NULL, last_history_id TEXT NOT NULL, label_id TEXT,
            connection_state TEXT NOT NULL CHECK(connection_state IN ('needs_label','active','revoked','error')),
            connected_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_gmail_mailboxes_email ON gmail_mailboxes(lower(email));
        CREATE TABLE IF NOT EXISTS query_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, query_id TEXT NOT NULL REFERENCES technical_queries(id) ON DELETE CASCADE,
            actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL, event TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
        );
        """)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(technical_queries)")
        }
        if "assignee_user_id" not in columns:
            conn.execute(
                "ALTER TABLE technical_queries ADD COLUMN assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL"
            )
        message_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(query_messages)")
        }
        if "raw_storage_ref" not in message_columns:
            conn.execute("ALTER TABLE query_messages ADD COLUMN raw_storage_ref TEXT")
        draft_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(query_drafts)")
        }
        if "citations_json" not in draft_columns:
            conn.execute(
                "ALTER TABLE query_drafts ADD COLUMN citations_json TEXT NOT NULL DEFAULT '[]'"
            )
        mailbox_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(gmail_mailboxes)")
        }
        if "label_id" not in mailbox_columns:
            conn.execute("ALTER TABLE gmail_mailboxes ADD COLUMN label_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tq_assignee_status ON technical_queries(assignee_user_id,status,updated_at DESC)"
        )


def _event(
    conn, query_id: str, event: str, actor: str | None, detail: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO query_events(query_id, actor_user_id, event, detail, created_at) VALUES (?,?,?,?,?)",
        (query_id, actor, event, detail, now()),
    )


def _source_supersession(conn, document_id: str) -> str:
    row = conn.execute(
        "SELECT superseded_by,confirmed_by FROM document_classification WHERE document_id=?",
        (document_id,),
    ).fetchone()
    if row and row["superseded_by"]:
        return "superseded"
    return "current" if row and row["confirmed_by"] else "unknown"


def _source_pages(conn, document_id: str, start: int, end: int):
    return conn.execute(
        "SELECT p.page_no,p.text AS native,p.needs_ocr,o.text AS ocr_text "
        "FROM pages p LEFT JOIN page_ocr o ON o.document_id=p.document_id AND o.page_no=p.page_no "
        "WHERE p.document_id=? AND p.page_no BETWEEN ? AND ? ORDER BY p.page_no",
        (document_id, start, end),
    ).fetchall()


def _page_text(row) -> str:
    return (row["ocr_text"] or "") if row["needs_ocr"] else (row["native"] or "")


def _squash(text: str | None) -> str:
    """Collapse every run of whitespace to one space. A PDF wraps a clause across
    lines ("film\nthickness") while a stored passage reads on one line; the words and
    numbers are the same. Only layout whitespace is ignored, never a character."""
    return " ".join((text or "").split())


def _quote_on_pages(conn, document_id: str, start: int, end: int, quote: str) -> bool:
    wanted = _squash(quote)
    if not wanted:
        return False
    return any(
        wanted in _squash(_page_text(row))
        for row in _source_pages(conn, document_id, start, end)
    )


def validate_send_evidence(
    item: dict[str, Any], allowed_document_ids: frozenset[str], unrestricted: bool
) -> None:
    """Check that approved source quotes remain readable and unreplaced."""
    with connect() as conn:
        for evidence in item.get("evidence", []):
            document_id = evidence["document_id"]
            if not unrestricted and document_id not in allowed_document_ids:
                raise PermissionError("source document access changed after approval")
            if (
                evidence["supersession_state"] == "superseded"
                or _source_supersession(conn, document_id) == "superseded"
            ):
                raise ValueError("a cited source has been superseded since approval")
            quote = evidence["exact_quote"]
            if not _quote_on_pages(
                conn, document_id, evidence["page_start"], evidence["page_end"], quote
            ):
                raise ValueError("a cited quote is no longer on its recorded page")


def _insert_attachments(
    conn, message_id: str, attachments: list[dict[str, Any]]
) -> None:
    for attachment in attachments:
        conn.execute(
            "INSERT INTO query_attachments(id,message_id,filename,media_type,size_bytes,sha256,storage_ref,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                message_id,
                attachment["filename"],
                attachment["media_type"],
                attachment["size_bytes"],
                attachment.get("sha256"),
                attachment.get("storage_ref"),
                now(),
            ),
        )


def _visible_where(
    user_id: str | None, is_admin: bool, unrestricted: bool
) -> tuple[str, list[Any]]:
    if unrestricted or is_admin:
        return "", []
    if user_id is None:
        return " WHERE 1 = 0", []
    return " WHERE (owner_user_id = ? OR assignee_user_id = ?)", [user_id, user_id]


def _filtered_where(
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    *,
    status: str | None = None,
    contractor: str | None = None,
    department: str | None = None,
    assignee_user_id: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
    evidence_state: str | None = None,
) -> tuple[str, list[Any]]:
    where, args = _visible_where(user_id, is_admin, unrestricted)
    filters = (
        ("status = ?", status),
        ("contractor_name = ?", contractor),
        ("department = ?", department),
        ("assignee_user_id = ?", assignee_user_id),
        ("received_at >= ?", received_from),
        ("received_at <= ?", received_to),
    )
    for clause, value in filters:
        if value is not None:
            where += " AND " if where else " WHERE "
            where += clause
            args.append(value)
    if evidence_state is not None:
        where += " AND " if where else " WHERE "
        where += "EXISTS (SELECT 1 FROM query_evidence e WHERE e.query_id=technical_queries.id AND e.evidence_state=?)"
        args.append(evidence_state)
    return where, args


def import_message(
    data: dict[str, Any],
    actor_user_id: str | None,
    is_admin: bool = False,
    unrestricted: bool = False,
) -> tuple[dict[str, Any], bool]:
    if data.get("provider") not in {"synthetic", "gmail", "microsoft_graph"}:
        raise ValueError("unknown message provider")
    received = data.get("received_at") or now()
    mailbox_id = data.get("mailbox_id") or ""
    qid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    with connect() as conn:
        existing = conn.execute(
            "SELECT query_id FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_message_id=?",
            (data["provider"], mailbox_id, data["provider_message_id"]),
        ).fetchone()
        if existing:
            visible = get(existing["query_id"], actor_user_id, is_admin, unrestricted)
            if visible is None:
                raise PermissionError("technical query is not visible to this user")
            return visible, True
        # A new provider message on the same thread is a follow-up, not a new
        # query. The provider message id remains unique, so retries still
        # collapse to the duplicate branch above.
        thread = data.get("provider_thread_id")
        threaded = None
        if thread:
            threaded = conn.execute(
                "SELECT query_id,from_address FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_thread_id=? ORDER BY received_at LIMIT 1",
                (data["provider"], mailbox_id, thread),
            ).fetchone()
            if (
                threaded
                and threaded["from_address"].strip().casefold()
                != data["from_address"].strip().casefold()
            ):
                threaded = None
        if threaded:
            visible = get(threaded["query_id"], actor_user_id, is_admin, unrestricted)
            if visible is None:
                raise PermissionError("technical query is not visible to this user")
            conn.execute(
                "INSERT INTO query_messages(id,query_id,provider,mailbox_id,provider_message_id,provider_thread_id,internet_message_id,from_address,to_addresses,cc_addresses,subject,body,sent_at,received_at,raw_message_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mid,
                    threaded["query_id"],
                    data["provider"],
                    mailbox_id,
                    data["provider_message_id"],
                    thread,
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
            conn.execute(
                "UPDATE query_messages SET raw_storage_ref=? WHERE id=?",
                (data.get("raw_storage_ref"), mid),
            )
            _insert_attachments(conn, mid, data.get("attachments", []))
            conn.execute(
                "UPDATE technical_queries SET status='triage',resolved_at=NULL,resolution_reason=NULL,updated_at=? "
                "WHERE id=? AND status NOT IN ('received','triage','cancelled')",
                (now(), threaded["query_id"]),
            )
            _event(
                conn,
                threaded["query_id"],
                "follow_up_received",
                actor_user_id,
                "provider thread matched",
            )
            return get(
                threaded["query_id"], actor_user_id, is_admin, unrestricted
            ) or {}, False
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
                mailbox_id,
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
        conn.execute(
            "UPDATE query_messages SET raw_storage_ref=? WHERE id=?",
            (data.get("raw_storage_ref"), mid),
        )
        _insert_attachments(conn, mid, data.get("attachments", []))
        _event(conn, qid, "received", actor_user_id, "provider message imported")
    return get(qid, actor_user_id, is_admin, unrestricted) or {}, False


def list_queries(
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    status: str | None = None,
    *,
    contractor: str | None = None,
    department: str | None = None,
    assignee_user_id: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
    evidence_state: str | None = None,
) -> list[dict[str, Any]]:
    where, args = _filtered_where(
        user_id,
        is_admin,
        unrestricted,
        status=status,
        contractor=contractor,
        department=department,
        assignee_user_id=assignee_user_id,
        received_from=received_from,
        received_to=received_to,
        evidence_state=evidence_state,
    )
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM technical_queries" + where + " ORDER BY updated_at DESC",
                args,
            ).fetchall()
        ]


def metrics(
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    *,
    contractor: str | None = None,
    department: str | None = None,
    assignee_user_id: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
    evidence_state: str | None = None,
) -> dict[str, int]:
    where, args = _filtered_where(
        user_id,
        is_admin,
        unrestricted,
        contractor=contractor,
        department=department,
        assignee_user_id=assignee_user_id,
        received_from=received_from,
        received_to=received_to,
        evidence_state=evidence_state,
    )
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM technical_queries"
            + where
            + " GROUP BY status",
            args,
        ).fetchall()
    result = dict.fromkeys(STATUSES, 0)
    result.update({row["status"]: row["count"] for row in rows})
    result["total"] = sum(result.values())
    return result


def assign_query(
    query_id: str,
    assignee_user_id: str,
    actor_user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if not (is_admin or unrestricted):
        raise PermissionError("an administrator is required to assign a query")
    with connect() as conn:
        if (
            conn.execute(
                "SELECT 1 FROM technical_queries WHERE id=?", (query_id,)
            ).fetchone()
            is None
        ):
            return None
        if (
            conn.execute(
                "SELECT 1 FROM users WHERE id=? AND is_active=1", (assignee_user_id,)
            ).fetchone()
            is None
        ):
            raise ValueError("assignee does not exist or is inactive")
        conn.execute(
            "UPDATE technical_queries SET assignee_user_id=?,updated_at=? WHERE id=?",
            (assignee_user_id, now(), query_id),
        )
        _event(
            conn, query_id, "assigned", actor_user_id, f"assignee={assignee_user_id}"
        )
    return get(query_id, actor_user_id, is_admin, unrestricted)


def triage_query(
    query_id: str,
    contractor_name: str | None,
    department: str | None,
    priority: str,
    due_at: str | None,
    actor_user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if not (is_admin or unrestricted):
        raise PermissionError("an administrator is required to triage a query")
    if priority not in {"low", "normal", "high", "urgent"}:
        raise ValueError("invalid priority")
    if due_at:
        try:
            datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("due date must be an ISO date or timestamp") from exc
    with connect() as conn:
        current = conn.execute(
            "SELECT status FROM technical_queries WHERE id=?", (query_id,)
        ).fetchone()
        if current is None:
            return None
        if current["status"] in {"duplicate", "cancelled"}:
            raise ValueError("this query cannot be triaged in its current state")
        status = "triage" if current["status"] == "received" else current["status"]
        conn.execute(
            "UPDATE technical_queries SET contractor_name=?,department=?,priority=?,due_at=?,status=?,updated_at=? WHERE id=?",
            (contractor_name, department, priority, due_at, status, now(), query_id),
        )
        _event(
            conn,
            query_id,
            "triaged",
            actor_user_id,
            json.dumps(
                {
                    "contractor_name": contractor_name,
                    "department": department,
                    "priority": priority,
                    "due_at": due_at,
                }
            ),
        )
    return get(query_id, actor_user_id, is_admin, unrestricted)


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
                    "SELECT a.*,d.status AS document_status FROM query_attachments a "
                    "LEFT JOIN documents d ON d.id=a.document_id WHERE a.message_id=?",
                    (message["id"],),
                )
            ]
            for attachment in message["attachments"]:
                if attachment["document_status"] == "ready":
                    attachment["parse_status"] = "ready"
                elif attachment["document_status"] in {"failed", "stored_not_indexed"}:
                    attachment["parse_status"] = attachment["document_status"]
        result["drafts"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_drafts WHERE query_id=? ORDER BY version",
                (query_id,),
            )
        ]
        result["evidence"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_evidence WHERE query_id=? ORDER BY created_at",
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
        result["sends"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_sends WHERE query_id=? ORDER BY created_at",
                (query_id,),
            )
        ]
        for send in result["sends"]:
            send["to_addresses"] = json.loads(send["to_addresses"] or "[]")
            send["cc_addresses"] = json.loads(send["cc_addresses"] or "[]")
        result["events"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM query_events WHERE query_id=? ORDER BY id", (query_id,)
            )
        ]
        return result


def add_evidence(
    query_id: str,
    document_id: str,
    exact_quote: str,
    page_start: int | None,
    page_end: int | None,
    locator: str | None,
    allowed_document_ids: frozenset[str],
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    actor_user_id: str | None,
) -> dict[str, Any] | None:
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] in {
        "send_pending",
        "sent",
        "awaiting_confirmation",
        "resolved",
    }:
        raise ValueError("sent query evidence is locked; import a follow-up first")
    if not unrestricted and document_id not in allowed_document_ids:
        raise PermissionError("source document is not readable")
    quote = exact_quote.strip()
    if not quote:
        raise ValueError("exact_quote is required")
    if page_start is None or page_end is None or page_end < page_start:
        raise ValueError("a valid source page range is required")
    with connect() as conn:
        if not _quote_on_pages(conn, document_id, page_start, page_end, quote):
            raise ValueError("exact_quote was not found in the selected source")
        evidence_id = str(uuid.uuid4())
        import hashlib

        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,locator,exact_quote,quote_hash,supersession_state,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                query_id,
                document_id,
                page_start,
                page_end,
                locator,
                quote,
                hashlib.sha256(quote.encode()).hexdigest(),
                _source_supersession(conn, document_id),
                now(),
            ),
        )
        conn.execute(
            "UPDATE technical_queries SET status='changes_requested',updated_at=? WHERE id=? AND status='approved'",
            (now(), query_id),
        )
        _event(
            conn,
            query_id,
            "evidence_added",
            actor_user_id,
            f"evidence={evidence_id};document={document_id}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def reconcile_send(
    query_id: str,
    send_id: str,
    outcome: str,
    provider_message_id: str | None,
    comment: str,
    actor_user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if not (is_admin or unrestricted):
        raise PermissionError("an administrator is required to reconcile a send")
    if outcome not in {"sent", "not_sent"} or not comment.strip():
        raise ValueError("a confirmed outcome and explanation are required")
    if outcome == "sent" and not provider_message_id:
        raise ValueError("the provider message id is required for a confirmed send")
    with connect() as conn:
        row = conn.execute(
            "SELECT state FROM query_sends WHERE id=? AND query_id=?",
            (send_id, query_id),
        ).fetchone()
        if row is None:
            return None
        if row["state"] != "uncertain":
            raise ValueError("only an uncertain send can be reconciled")
        conn.execute(
            "UPDATE query_sends SET state=?,provider_message_id=?,error=NULL WHERE id=?",
            (
                "sent" if outcome == "sent" else "confirmed_not_sent",
                provider_message_id,
                send_id,
            ),
        )
        conn.execute(
            "UPDATE technical_queries SET status=?,updated_at=? WHERE id=?",
            ("sent" if outcome == "sent" else "approved", now(), query_id),
        )
        _event(
            conn,
            query_id,
            "send_reconciled",
            actor_user_id,
            f"outcome={outcome};send={send_id};comment={comment.strip()[:500]}",
        )
    return get(query_id, actor_user_id, is_admin, unrestricted)


def update_evidence(
    query_id: str,
    evidence_id: str,
    evidence_state: str,
    supersession_state: str,
    conflict_group: str | None,
    actor_user_id: str | None,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if evidence_state not in {"verified", "missing", "conflicting", "ambiguous"}:
        raise ValueError("unknown evidence state")
    if supersession_state not in {"current", "superseded", "unknown"}:
        raise ValueError("unknown supersession state")
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] in {
        "send_pending",
        "sent",
        "awaiting_confirmation",
        "resolved",
    }:
        raise ValueError("sent query evidence is locked; import a follow-up first")
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM query_evidence WHERE id=? AND query_id=?",
            (evidence_id, query_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE query_evidence SET evidence_state=?,supersession_state=?,conflict_group=? WHERE id=?",
            (evidence_state, supersession_state, conflict_group, evidence_id),
        )
        conn.execute(
            "UPDATE technical_queries SET status='changes_requested',updated_at=? WHERE id=? AND status='approved'",
            (now(), query_id),
        )
        _event(
            conn,
            query_id,
            "evidence_classified",
            actor_user_id,
            f"evidence={evidence_id};state={evidence_state};supersession={supersession_state}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def prepare_evidence(
    query_id: str,
    allowed_document_ids: frozenset[str],
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    actor_user_id: str | None,
) -> dict[str, Any] | None:
    """Extract a conservative question and prepare evidence without generating an answer."""
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] not in {"received", "triage", "drafting", "changes_requested"}:
        raise ValueError("evidence cannot be prepared in the current query state")
    message = (current.get("messages") or [{}])[0]
    body = (message.get("body") or "").strip()
    saved_question = current.get("extracted_question") or ""
    question = body if "[Attachment " in saved_question else saved_question or body
    marker = body.upper().find("QUESTION")
    if not current.get("extracted_question") and marker >= 0:
        question = body[marker:].split(":", 1)[-1].strip()
    attachment_ids = {
        attachment["document_id"]
        for message_row in current.get("messages", [])
        for attachment in message_row.get("attachments", [])
        if attachment.get("document_id")
        and (unrestricted or attachment["document_id"] in allowed_document_ids)
    }
    attachment_sections: list[str] = []
    with connect() as conn:
        for attachment in message.get("attachments", []):
            document_id = attachment.get("document_id")
            if (
                not document_id
                or document_id not in attachment_ids
                or attachment.get("document_status") != "ready"
            ):
                continue
            pages = _source_pages(conn, document_id, 1, 5)
            for page in pages:
                text = _page_text(page).strip()
                if text:
                    attachment_sections.append(
                        f"[Attachment {attachment['filename']}, page {page['page_no']}]\n{text}"
                    )
    if attachment_sections:
        question = "\n\n".join([question, *attachment_sections]).strip()
        if len(question) > 12_000:
            question = (
                question[:12_000].rstrip()
                + "\n[More attachment text exists; open the original PDF.]"
            )
    elif not question and message.get("attachments"):
        raise ValueError(
            "the attached question is not readable yet; wait for PDF processing or OCR"
        )
    if not question:
        raise ValueError("the query contains no extractable question")
    from . import search

    # The query's own attachments are context, never an authority, so they must not
    # take a place among the few results: search everything else the caller may read.
    field = search.search(
        question,
        limit=5,
        rerank=False,
        dense=False,
        allowed_document_ids=frozenset(allowed_document_ids) - attachment_ids,
    )
    # `search.search` returns its results under "hits" (answer.answer uses "passages").
    hits = field.get("hits") or []
    with connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET extracted_question=?,status='drafting',updated_at=? WHERE id=?",
            (question, now(), query_id),
        )
        for passage in hits[:5]:
            quote = (passage.get("text") or "").strip()
            if not quote:
                continue
            if passage.get("page_start") is None or passage.get("page_end") is None:
                continue
            if (
                not unrestricted
                and passage.get("document_id") not in allowed_document_ids
            ):
                continue
            if passage.get("document_id") in attachment_ids:
                # The contractor's question is context, not an authority for its answer.
                continue
            if not _quote_on_pages(
                conn,
                passage["document_id"],
                passage["page_start"],
                passage["page_end"],
                quote,
            ):
                continue
            import hashlib

            quote_hash = hashlib.sha256(quote.encode()).hexdigest()
            known = conn.execute(
                "SELECT id,supersession_state FROM query_evidence WHERE query_id=? "
                "AND document_id=? AND quote_hash=? AND page_start IS ? AND page_end IS ?",
                (
                    query_id,
                    passage["document_id"],
                    quote_hash,
                    passage.get("page_start"),
                    passage.get("page_end"),
                ),
            ).fetchone()
            if known:
                # Preparing again must not stack up copies of the same passage, but the
                # source's standing may have changed since the row was made: a newly
                # superseded source is always recorded; "unknown" becomes "current" once
                # an engineer has confirmed the document. Nothing else is overwritten.
                standing = _source_supersession(conn, passage["document_id"])
                if standing == "superseded" or (
                    known["supersession_state"] == "unknown" and standing == "current"
                ):
                    conn.execute(
                        "UPDATE query_evidence SET supersession_state=? WHERE id=?",
                        (standing, known["id"]),
                    )
                continue
            evidence_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,locator,exact_quote,quote_hash,supersession_state,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    query_id,
                    passage["document_id"],
                    passage.get("page_start"),
                    passage.get("page_end"),
                    passage.get("locator"),
                    quote,
                    quote_hash,
                    _source_supersession(conn, passage["document_id"]),
                    now(),
                ),
            )
        _event(
            conn,
            query_id,
            "evidence_prepared",
            actor_user_id,
            f"passages={len(hits)}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def add_draft(
    query_id: str,
    answer: str,
    assumptions: list[str],
    unresolved: list[str],
    actor_user_id: str | None,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    *,
    citations: list[dict[str, Any]] | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any] | None:
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] not in {"received", "triage", "drafting", "changes_requested"}:
        raise ValueError("a draft cannot be added in the current query state")
    with connect() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS v FROM query_drafts WHERE query_id=?",
            (query_id,),
        ).fetchone()["v"]
        did = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO query_drafts(id,query_id,version,answer,assumptions_json,unresolved_json,citations_json,model,prompt_version,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                did,
                query_id,
                version,
                answer,
                json.dumps(assumptions),
                json.dumps(unresolved),
                json.dumps(citations or []),
                model,
                prompt_version,
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
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] in {
        "send_pending",
        "sent",
        "awaiting_confirmation",
        "resolved",
    }:
        raise ValueError("sent query attachments are locked; import a follow-up first")
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM query_attachments WHERE id=? AND message_id IN "
            "(SELECT id FROM query_messages WHERE query_id=?)",
            (attachment_id, query_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE query_attachments SET document_id=?, scan_status='not_scanned', parse_status='pending' WHERE id=?",
            (document_id, attachment_id),
        )
        conn.execute(
            "UPDATE technical_queries SET status='changes_requested',updated_at=? WHERE id=? AND status='approved'",
            (now(), query_id),
        )
        _event(
            conn,
            query_id,
            "attachment_linked",
            actor_user_id,
            f"attachment={attachment_id};document={document_id}",
        )
    return get(query_id, user_id, is_admin, unrestricted)


def attachment_for_query(
    query_id: str,
    attachment_id: str,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
) -> dict[str, Any] | None:
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT a.* FROM query_attachments a JOIN query_messages m ON m.id=a.message_id "
            "WHERE m.query_id=? AND a.id=?",
            (query_id, attachment_id),
        ).fetchone()
    return dict(row) if row else None


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
    if not (is_admin or unrestricted):
        raise PermissionError("an authorised reviewer is required")
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    current = get(query_id, user_id, is_admin, unrestricted)
    allowed = {
        "request_changes": {"awaiting_review", "changes_requested"},
        "approve": {"awaiting_review"},
        "reject": {"awaiting_review", "changes_requested"},
        "close": {"sent", "awaiting_confirmation"},
    }
    if current is not None and current["status"] not in allowed[decision]:
        raise ValueError(
            f"decision {decision} is not allowed in state {current['status']}"
        )
    if decision in {"approve", "request_changes", "reject"}:
        latest = current["drafts"][-1] if current and current["drafts"] else None
        if latest is None or draft_id != latest["id"]:
            raise ValueError("the decision must name the latest draft")
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
