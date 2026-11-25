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


#: The capability that makes a person a qualified technical-query reviewer. It is
#: NOT implied by `admin`: an administrator runs the system, and an administrator's
#: account alone proves nothing about engineering qualification.
REVIEWER_CAPABILITY = "technical_query_reviewer"
REVIEWER_DESCRIPTION = "Confirm questions, review evidence, approve and send technical query responses"
#: Evidence states. `needs_review` is set by the system on a source it no longer
#: trusts; only a reviewer can move a row out of it.
#: `proposed` is a passage the SEARCH found: its quote is checked by code to stand on the page, but no person has judged that it answers the
#: question. Only a reviewer moves it to `verified` (or rejects it); until then it blocks approval and send (reviewer's blocker B5).
EVIDENCE_STATES = ("verified", "missing", "conflicting", "ambiguous", "needs_review", "proposed", "rejected")


#: Evidence in these states is unresolved: a response resting on it is neither approved nor sent.
UNRESOLVED_EVIDENCE_STATES = ("needs_review", "proposed", "conflicting", "ambiguous")


def unresolved_evidence_message(state: str, action: str) -> str:
    if state == "proposed":
        return f"a passage found by the system is not yet kept as evidence by a reviewer, which must happen before {action}"
    if state == "needs_review":
        return f"evidence from a contractor attachment needs a reviewer's decision before {action}"
    return f"evidence marked {state} must be resolved by a reviewer before {action}"


def is_reviewer(capabilities: frozenset[str] | set[str], unrestricted: bool = False) -> bool:
    return unrestricted or REVIEWER_CAPABILITY in capabilities


def _require_reviewer(reviewer: bool, unrestricted: bool, what: str) -> None:
    if not (reviewer or unrestricted):
        raise PermissionError(f"a qualified technical-query reviewer is required to {what}")


_READY_FOR: str | None = None

OFF_WORDS = "Technical queries are switched off on this server."


CLAUDE_DRAFT_OFF_WORDS = "Claude for the draft is not enabled on this server."
#: Sending an answer by email is NOT approved by the owner (25 Nov 2026) and there is NO code that sends: the Gmail client has no send call,
#: the scope asked of Google is read-only, and the send route only refuses. No setting lifts this: it takes the owner's written "sending
#: approved" and a code change with a second Google consent.
SEND_OFF_WORDS = "Sending is not approved by the owner: the answer is prepared as a Word file, never emailed."


class FeatureOff(RuntimeError):
    """The technical-query feature is switched off (`TECHNICAL_QUERIES_ENABLED`); nothing was done."""


def enabled() -> bool:
    """The ONE way-back switch of the whole feature (routes, mailbox poller, Gmail sockets, menu entry). Default off."""
    from .config import settings

    return bool(settings.technical_queries_enabled)


def require_enabled() -> None:
    """Raise `FeatureOff` when the switch is off. Every Gmail call that would open a socket asks this first."""
    if not enabled():
        raise FeatureOff(OFF_WORDS)


def ensure_ready() -> None:
    """Switch off: 404, nothing done (not even the tables). On: create the tables once per database. The app does it at start; this
    makes every route safe on a database the start-up step never saw (a test, a restored copy, a new data folder)."""
    from fastapi import HTTPException

    from .config import settings

    if not enabled():
        raise HTTPException(status_code=404, detail=OFF_WORDS)
    if str(settings.db_path) != _READY_FOR:
        ensure_schema()


def ensure_schema() -> None:
    """Create the tables and bring them up to date. Memoised per database by `ensure_ready`, so a
    request made after start-up writes nothing."""
    global _READY_FOR
    from .config import settings

    _ensure_schema()
    _READY_FOR = str(settings.db_path)


def _ensure_schema() -> None:
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
        CREATE TABLE IF NOT EXISTS query_routing_rules (
            id TEXT PRIMARY KEY, match_type TEXT NOT NULL CHECK(match_type IN ('address','domain')),
            match_value TEXT NOT NULL, contractor_name TEXT, department TEXT,
            created_by TEXT REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL,
            UNIQUE(match_type, match_value)
        );
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
        from . import gmail_import_jobs, technical_query_jobs

        technical_query_jobs.create_table(conn)
        gmail_import_jobs.create_tables(conn)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(technical_queries)")
        }
        if "assignee_user_id" not in columns:
            conn.execute(
                "ALTER TABLE technical_queries ADD COLUMN assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL"
            )
        for column in ("ref_key", "ref_type", "ref_number", "discipline_code", "title_short"):  # read from the subject by code
            if column not in columns:
                conn.execute(f"ALTER TABLE technical_queries ADD COLUMN {column} TEXT")
        if "needs_person" not in columns:
            conn.execute("ALTER TABLE technical_queries ADD COLUMN needs_person INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_technical_queries_ref ON technical_queries(ref_key)")
        for column in (
            "routing_source",
            "attachment_context",
            "proposed_question",
            "proposed_questions",
            "proposal_note",
            "evidence_coverage",
            "attachment_reading",
            "confirmed_question",
            "confirmed_question_by",
            "confirmed_question_at",
        ):
            if column not in columns:
                conn.execute(f"ALTER TABLE technical_queries ADD COLUMN {column} TEXT")
        attachment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(query_attachments)")
        }
        if "scan_detail" not in attachment_columns:
            conn.execute("ALTER TABLE query_attachments ADD COLUMN scan_detail TEXT")
        for column in ("filed_at", "filed_by"):  # set when an engineer files the attachment into the library on purpose
            if column not in attachment_columns:
                conn.execute(f"ALTER TABLE query_attachments ADD COLUMN {column} TEXT")
        evidence_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(query_evidence)")
        }
        if "attachment_checked_at" not in evidence_columns:
            conn.execute("ALTER TABLE query_evidence ADD COLUMN attachment_checked_at TEXT")
        # A database without the roles table has no users to grant the role to.
        has_roles = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roles'"
        ).fetchone()
        if has_roles and conn.execute(
            "SELECT 1 FROM roles WHERE name=?", (REVIEWER_CAPABILITY,)
        ).fetchone() is None:
            conn.execute(
                "INSERT INTO roles(id,name,description,kind,created_at) VALUES (?,?,?,?,?)",
                (
                    f"role_{REVIEWER_CAPABILITY}",
                    REVIEWER_CAPABILITY,
                    REVIEWER_DESCRIPTION,
                    "capability",
                    now(),
                ),
            )
        invalidate_attachment_evidence(conn)
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


def invalidate_attachment_evidence(conn, query_id: str | None = None) -> int:
    """Evidence taken from a contractor's own attachment is not an authority. Rows
    saved before that rule existed are moved to `needs_review` once; a reviewer then
    keeps or rejects each one. The row is stamped so a deliberate decision is never
    undone by a later sweep, and a row an engineer added from an attachment by hand
    is stamped when it is made."""
    marks = "SELECT DISTINCT document_id FROM query_attachments WHERE document_id IS NOT NULL"
    where = "evidence_state='verified' AND attachment_checked_at IS NULL AND document_id IN (" + marks + ")"
    args: list[Any] = [now()]
    if query_id is not None:
        where += " AND query_id=?"
        args.append(query_id)
    return conn.execute(
        "UPDATE query_evidence SET evidence_state='needs_review',attachment_checked_at=? WHERE " + where,
        args,
    ).rowcount


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


def _static_check_for(conn, document_id: str) -> dict[str, Any]:
    """The honest result for a stored file: checked, or not checked when it cannot be found."""
    from pathlib import Path

    from . import attachment_safety, stored_paths

    row = conn.execute("SELECT stored_path FROM documents WHERE id=?", (document_id,)).fetchone()
    local = stored_paths.local(row["stored_path"]) if row else None
    if not local or not Path(local).is_file():
        return {"status": attachment_safety.NOT_SCANNED, "findings": []}
    return attachment_safety.check_pdf(local)


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
            if evidence.get("evidence_state") in UNRESOLVED_EVIDENCE_STATES:
                raise ValueError(
                    unresolved_evidence_message(evidence["evidence_state"], "sending")
                )
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
    ref_type: str | None = None,
    discipline: str | None = None,
    number: str | None = None,
    needs_person: bool | None = None,
) -> tuple[str, list[Any]]:
    where, args = _visible_where(user_id, is_admin, unrestricted)
    filters = (
        ("status = ?", status),
        ("contractor_name = ?", contractor),
        ("department = ?", department),
        ("assignee_user_id = ?", assignee_user_id),
        ("received_at >= ?", received_from),
        ("received_at <= ?", received_to),
        ("ref_type = ?", ref_type.upper() if ref_type else None),
        ("discipline_code = ?", discipline.upper() if discipline else None),
        ("ref_number = ?", str(int(number)) if number and str(number).strip().isdigit() else None),
        ("needs_person = ?", None if needs_person is None else int(needs_person)),
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
    if data.get("provider") not in {"synthetic", "gmail", "microsoft_graph", "manual"}:
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
        from . import technical_query_subject

        ref = technical_query_subject.parse(data.get("subject"))
        if ref and ref["prefixed"]:  # the full number in the subject IS the query's identity: a forward or a reply with the same reference joins the same query, in the same mailbox only
            same = conn.execute(
                "SELECT q.id FROM technical_queries q WHERE q.ref_key=? AND EXISTS (SELECT 1 FROM query_messages m WHERE m.query_id=q.id AND m.mailbox_id IS ?) "
                "ORDER BY q.created_at LIMIT 1",
                (ref["reference"], mailbox_id),
            ).fetchone()
            if same:
                threaded = {"query_id": same["id"], "from_address": data["from_address"]}
        if thread and not threaded:
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
        contractor, department, routed_by = _routed(
            conn, data["from_address"], data.get("contractor_name"), data.get("department")
        )
        conn.execute(
            "INSERT INTO technical_queries(id,owner_user_id,contractor_name,department,routing_source,subject,extracted_question,status,priority,received_at,created_at,updated_at,ref_key,ref_type,ref_number,discipline_code,title_short,needs_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                qid,
                actor_user_id,
                contractor,
                department,
                routed_by,
                data["subject"],
                data.get("question"),
                "received",
                data.get("priority", "normal"),
                received,
                now(),
                now(),
                ref["reference"] if ref and ref["prefixed"] else None,  # a bare number is not an identity: no key, so nothing can join it
                ref["type"] if ref else None,
                ref["number"] if ref else None,
                ref["discipline"] if ref else None,
                ref["title"] if ref else None,
                0 if ref and ref["prefixed"] else 1,  # no number, or a bare one, in the subject: kept, and flagged for a person; never dropped
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
    ref_type: str | None = None,
    discipline: str | None = None,
    number: str | None = None,
    needs_person: bool | None = None,
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
        ref_type=ref_type,
        discipline=discipline,
        number=number,
        needs_person=needs_person,
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
            "UPDATE technical_queries SET contractor_name=?,department=?,routing_source='manual',priority=?,due_at=?,status=?,updated_at=? WHERE id=?",
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
        try:
            result["attachment_context"] = json.loads(
                result.get("attachment_context") or "[]"
            )
        except ValueError:
            result["attachment_context"] = []
        for name, empty in (("proposed_questions", []), ("evidence_coverage", None), ("attachment_reading", [])):
            try:
                result[name] = json.loads(result.get(name) or "null") or empty
            except ValueError:
                result[name] = empty
        from . import technical_query_jobs

        result["evidence_job"] = technical_query_jobs.latest(conn, query_id)
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
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,locator,exact_quote,quote_hash,supersession_state,created_at,attachment_checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                now(),  # chosen by a person, so it is not swept as an automatic find
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
    *,
    reviewer: bool = False,
) -> dict[str, Any] | None:
    _require_reviewer(reviewer, unrestricted, "change evidence")
    if evidence_state not in EVIDENCE_STATES:
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


_ATTACHMENT_MARK = "\n\n[Attachment "
MAX_PROPOSED_QUESTION = 12_000
#: Only this many pages of each attachment are read for questions; the screen says which pages were not read (completeness rule).
ATTACHMENT_PAGES_READ = 5
CUT_MARK = " [cut here: the wording was longer than the limit; the rest is on the attachment pages]"
MAX_CONFIRMED_QUESTION = 5_000


def unfiled_attachment_ids(conn) -> frozenset[str]:
    """The FLAG: documents that arrived as a technical-query attachment and that nobody has filed into the library. They are kept out of
    library search, Chat, the review picker and every automatic Claude-approval route (the scope of every request leaves them out:
    `access.scope_for_user`), until an engineer files one on purpose with a role (`file_into_library`). Reads only: with the feature never
    switched on there is no table and the answer is empty."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_attachments'").fetchone() is None:
        return frozenset()
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(query_attachments)")}
    if "filed_at" not in columns:
        return frozenset(r["document_id"] for r in conn.execute("SELECT DISTINCT document_id FROM query_attachments WHERE document_id IS NOT NULL"))
    return frozenset(
        r["document_id"]
        for r in conn.execute(
            "SELECT DISTINCT document_id FROM query_attachments WHERE document_id IS NOT NULL AND document_id NOT IN "
            "(SELECT document_id FROM query_attachments WHERE document_id IS NOT NULL AND filed_at IS NOT NULL)"
        )
    )


def mark_filed(conn, document_id: str, user_id: str | None) -> None:
    conn.execute(
        "UPDATE query_attachments SET filed_at=?, filed_by=? WHERE document_id=? AND filed_at IS NULL", (now(), user_id, document_id)
    )


def file_into_library(document_id: str, role: str, user_id: str | None) -> bool:
    """File an unfiled attachment document into the library on purpose, with a role (an engineer's act). The role goes through the one
    `classification.set_role`, which brings the ordinary hooks (extraction, the approval check of the role) with it. False when the
    document is not an unfiled technical-query attachment."""
    from . import classification

    with connect() as conn:
        if document_id not in unfiled_attachment_ids(conn):
            return False
    if role:
        classification.set_role(document_id, role)
    with connect() as conn:
        mark_filed(conn, document_id, user_id)
    from . import claude_auto_approve

    claude_auto_approve.on_upload(document_id)  # now an ordinary library document: the approval routes look at it by its role
    return True


def file_if_unfiled_attachment(document_id: str, scope, role: str | None) -> bool:
    """An ORDINARY UPLOAD of a file already held as an unfiled technical-query attachment FILES it (the person uploaded it on purpose): the
    filing is stamped, and the role the uploader chose (if any) is set through `classification.set_role`. Only for a person who may read
    that attachment (a stranger is told "awaiting grant", as for any held document they may not read). True when it was filed now."""
    if not scope.may_read_attachment(document_id) or scope.may_read(document_id):
        return False
    return file_into_library(document_id, role or "", scope.user_id)


def query_attachment_document_ids(conn) -> frozenset[str]:
    """Every document that arrived as a query attachment, from any query. A
    contractor's attachment is context for its own query, never an authority for
    anyone's answer, so none of them is searched as evidence."""
    return frozenset(
        row["document_id"]
        for row in conn.execute(
            "SELECT DISTINCT document_id FROM query_attachments WHERE document_id IS NOT NULL"
        )
    )


def original_email_question(saved: str | None) -> str:
    """The email's own question. Older rows stored the email question and the
    attachment text joined under "[Attachment ...]" labels; only the first part is
    the email's."""
    text = (saved or "").strip()
    cut = text.find(_ATTACHMENT_MARK)
    if cut >= 0:
        return text[:cut].strip()
    if text.startswith("[Attachment "):
        return ""
    return text


def propose_question(email_question: str, proposals: list[dict[str, Any]] | None = None) -> str:
    """The wording evidence is searched for until an engineer confirms one: the email's own question, then the questions the model found in
    the attachment that the email does not already say, each numbered on its own line. No attachment page is copied in bulk (F4), and no
    label or file name. It is a proposal, not an answer to anything."""
    own = (email_question or "").strip()
    lines = [own] if own else []
    said = _squash(own).casefold()
    extra = [p["question"] for p in proposals or [] if _squash(p["question"]).casefold() not in said]
    lines += [f"{n}. {q}" for n, q in enumerate(extra, 1)]
    text = "\n".join(lines)
    if len(text) > MAX_PROPOSED_QUESTION:
        text = text[:MAX_PROPOSED_QUESTION].rstrip() + CUT_MARK
    return text


def confirm_question(
    query_id: str,
    question: str,
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    actor_user_id: str | None,
    *,
    reviewer: bool = False,
) -> dict[str, Any] | None:
    _require_reviewer(reviewer, unrestricted, "confirm a question")
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] not in {"received", "triage", "drafting", "changes_requested"}:
        raise ValueError("the question cannot be confirmed in the current query state")
    text = question.strip()
    if not text:
        raise ValueError("the confirmed question cannot be empty")
    if len(text) > MAX_CONFIRMED_QUESTION:
        raise ValueError(
            f"the confirmed question is longer than {MAX_CONFIRMED_QUESTION} characters"
        )
    with connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET confirmed_question=?,confirmed_question_by=?,"
            "confirmed_question_at=?,updated_at=? WHERE id=?",
            (text, actor_user_id, now(), now(), query_id),
        )
        _event(conn, query_id, "question_confirmed", actor_user_id, f"chars={len(text)}")
    return get(query_id, user_id, is_admin, unrestricted)


def prepare_evidence(
    query_id: str,
    allowed_document_ids: frozenset[str],
    user_id: str | None,
    is_admin: bool,
    unrestricted: bool,
    actor_user_id: str | None,
    *,
    progress=None,
) -> dict[str, Any] | None:
    """Extract a conservative question and prepare evidence without generating an answer. `progress(done, total, label)` is told how far
    each of the two long steps has got (the technical-query job shows it)."""
    current = get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    if current["status"] not in {"received", "triage", "drafting", "changes_requested"}:
        raise ValueError("evidence cannot be prepared in the current query state")
    with connect() as conn:
        invalidate_attachment_evidence(conn, query_id)
    message = (current.get("messages") or [{}])[0]
    body = (message.get("body") or "").strip()
    saved_question = original_email_question(current.get("extracted_question"))
    email_question = saved_question or body
    marker = body.upper().find("QUESTION")
    if not saved_question and marker >= 0:
        email_question = body[marker:].split(":", 1)[-1].strip()
    attachment_ids = {
        attachment["document_id"]
        for message_row in current.get("messages", [])
        for attachment in message_row.get("attachments", [])
        if attachment.get("document_id")
        and (unrestricted or attachment["document_id"] in allowed_document_ids)
    }
    context: list[dict[str, Any]] = []
    reading: list[dict[str, Any]] = []
    with connect() as conn:
        for attachment in message.get("attachments", []):
            document_id = attachment.get("document_id")
            if (
                not document_id
                or document_id not in attachment_ids
                or attachment.get("document_status") != "ready"
                or attachment.get("scan_status") == "static_check_flagged"
            ):
                continue
            total = conn.execute("SELECT page_count FROM documents WHERE id=?", (document_id,)).fetchone()
            total_pages = int((total["page_count"] if total else 0) or 0)
            read_to = min(ATTACHMENT_PAGES_READ, total_pages or ATTACHMENT_PAGES_READ)
            reading.append(
                {
                    "filename": attachment["filename"],
                    "pages_read": read_to,
                    "page_count": total_pages or None,
                    "line": f"{attachment['filename']}: pages 1 to {read_to}"
                    + (f" of {total_pages} read" if total_pages else " read")
                    + (f"; pages {read_to + 1} to {total_pages} were not read" if total_pages > read_to else "")
                    + ".",
                }
            )
            for page in _source_pages(conn, document_id, 1, ATTACHMENT_PAGES_READ):
                text = _page_text(page).strip()
                if text:
                    context.append(
                        {
                            "filename": attachment["filename"],
                            "page": page["page_no"],
                            "text": text,
                        }
                    )
    from . import technical_query_questions

    proposals, proposal_note = technical_query_questions.from_pages(context, progress)
    proposal = propose_question(email_question, proposals)
    # An engineer's confirmed wording, when there is one, is what evidence is found for.
    question = current.get("confirmed_question") or proposal
    if not question:
        if proposal_note == technical_query_questions.MODEL_UNAVAILABLE:
            raise ValueError(
                "no question could be proposed because the local model cannot answer right now; write the question and confirm it"
            )
        if message.get("attachments"):
            raise ValueError(
                "the attached question is not readable yet; wait for PDF processing or OCR"
            )
        raise ValueError("the query contains no extractable question")
    from . import technical_query_contracts

    # The query's own attachments are context, never an authority, so they are never searched: every CONTRACT the caller may read is
    # searched on its own (dense + rerank), and the coverage is stored beside the passages.
    with connect() as conn:
        attachment_documents = query_attachment_document_ids(conn)
    field = technical_query_contracts.search_all(
        question[:MAX_PROPOSED_QUESTION], frozenset(allowed_document_ids) - attachment_documents, progress
    )
    coverage = field["coverage"]
    hits = field.get("hits") or []
    with connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET extracted_question=?,attachment_context=?,"
            "proposed_question=?,proposed_questions=?,proposal_note=?,evidence_coverage=?,attachment_reading=?,status='drafting',updated_at=? WHERE id=?",
            (
                email_question or None,
                json.dumps(context),
                proposal,
                json.dumps(proposals),
                proposal_note or None,
                json.dumps(coverage),
                json.dumps(reading),
                now(),
                query_id,
            ),
        )
        for passage in hits[: technical_query_contracts.MAX_PASSAGES]:
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
            if passage.get("document_id") in attachment_documents:
                # A contractor's attachment is context, not an authority for any answer.
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
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,locator,exact_quote,quote_hash,evidence_state,supersession_state,created_at) VALUES (?,?,?,?,?,?,?,?,'proposed',?,?)",
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
            f"passages={len(hits)}; {coverage['line']}",
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
        scan = _static_check_for(conn, document_id)
        conn.execute(
            "UPDATE query_attachments SET document_id=?, scan_status=?, scan_detail=?, parse_status='pending' WHERE id=?",
            (document_id, scan["status"], json.dumps(scan["findings"]), attachment_id),
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
    *,
    reviewer: bool = False,
) -> dict[str, Any] | None:
    if decision not in {"request_changes", "approve", "reject", "close"}:
        raise ValueError("unknown technical-query decision")
    _require_reviewer(reviewer, unrestricted, "decide on a response")
    if get(query_id, user_id, is_admin, unrestricted) is None:
        return None
    current = get(query_id, user_id, is_admin, unrestricted)
    if decision == "approve" and current is not None:
        for row in current.get("evidence", []):
            if row["evidence_state"] in UNRESOLVED_EVIDENCE_STATES:
                raise ValueError(unresolved_evidence_message(row["evidence_state"], "approval"))

    allowed = {
        "request_changes": {"awaiting_review", "changes_requested"},
        "approve": {"awaiting_review"},
        "reject": {"awaiting_review", "changes_requested"},
        "close": {"approved", "sent", "awaiting_confirmation"},  # approved: the engineer handed the Word file over; nothing is emailed from here
    }
    if current is not None and current["status"] not in allowed[decision]:
        raise ValueError(
            f"decision {decision} is not allowed in state {current['status']}"
        )
    if decision in {"approve", "request_changes", "reject"}:
        latest = current["drafts"][-1] if current and current["drafts"] else None
        if latest is None or draft_id != latest["id"]:
            raise ValueError("the decision must name the latest draft")
        if decision == "approve":
            _require_cited(current)
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


def _require_cited(current: dict[str, Any]) -> None:
    """A draft is approved only if its latest version cites at least one passage that is verified, current evidence of this query: a claim
    with no citation that resolves is never approved (rule 4; reviewer's M7)."""
    latest = current["drafts"][-1] if current.get("drafts") else None
    try:
        cited = json.loads((latest or {}).get("citations_json") or "[]")
    except ValueError:
        cited = []
    good = {
        row["id"]
        for row in current.get("evidence", [])
        if row["evidence_state"] == "verified" and row["supersession_state"] == "current"
    }
    if not any(isinstance(c, dict) and c.get("evidence_id") in good for c in cited):
        raise ValueError("the draft cites no verified, current evidence of this query; add a citation before approval")


def list_reviewers() -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT u.id,u.display_name,u.email FROM users u "
                "JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id "
                "WHERE r.name=? AND r.kind='capability' ORDER BY u.display_name",
                (REVIEWER_CAPABILITY,),
            )
        ]


def set_reviewer(user_id: str, granted: bool, actor: dict[str, Any]) -> bool:
    """Grant or revoke the reviewer capability. Recorded in the admin audit log. An
    administrator cannot grant it to themselves: qualification is another person's call."""
    from .admin import _audit

    if granted and actor.get("id") == user_id:
        raise PermissionError("an administrator cannot grant themselves the reviewer role")
    with connect() as conn:
        role = conn.execute(
            "SELECT id FROM roles WHERE name=? AND kind='capability'", (REVIEWER_CAPABILITY,)
        ).fetchone()
        if role is None:
            raise ValueError("the reviewer role is not configured")
        if conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
            return False
        if granted:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)",
                (user_id, role["id"], now()),
            )
        else:
            conn.execute(
                "DELETE FROM user_roles WHERE user_id=? AND role_id=?", (user_id, role["id"])
            )
        _audit(
            "technical_query_reviewer_granted" if granted else "technical_query_reviewer_revoked",
            actor, "user", user_id, "ok", f"role={REVIEWER_CAPABILITY}", conn=conn,
        )
    return True


#: Public mail services say nothing about which company a sender works for, so no rule may
#: route on one of these domains. An exact address can still be routed.
PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
        "yahoo.com", "ymail.com", "icloud.com", "me.com", "aol.com", "proton.me",
        "protonmail.com", "gmx.com", "mail.com", "zoho.com",
    }
)


def _address_parts(address: str) -> tuple[str, str]:
    value = (address or "").strip().casefold()
    if "<" in value and ">" in value:
        value = value[value.rindex("<") + 1 : value.rindex(">")].strip()
    return value, value.rpartition("@")[2]


def _routed(conn, from_address: str, contractor: str | None, department: str | None):
    """Fill only the blank fields from the most specific matching rule. Whatever the
    message already carried is kept. Returns (contractor, department, source)."""
    if contractor and department:
        return contractor, department, None
    address, domain = _address_parts(from_address)
    rule = conn.execute(
        "SELECT * FROM query_routing_rules WHERE match_type='address' AND match_value=?",
        (address,),
    ).fetchone() or conn.execute(
        "SELECT * FROM query_routing_rules WHERE match_type='domain' AND match_value=?",
        (domain,),
    ).fetchone()
    if rule is None:
        return contractor, department, None
    return (
        contractor or rule["contractor_name"],
        department or rule["department"],
        f"rule:{rule['id']}",
    )


def list_routing_rules() -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM query_routing_rules ORDER BY match_type,match_value"
            )
        ]


def set_routing_rule(
    match_type: str,
    match_value: str,
    contractor_name: str | None,
    department: str | None,
    actor_user_id: str | None,
    is_admin: bool,
) -> list[dict[str, Any]]:
    if not is_admin:
        raise PermissionError("an administrator is required to change routing rules")
    value = (match_value or "").strip().casefold().lstrip("@")
    if match_type not in {"address", "domain"} or not value:
        raise ValueError("a rule names an address or a domain")
    if match_type == "address" and ("@" not in value or value.startswith("@")):
        raise ValueError("an address rule needs a full email address")
    if match_type == "domain" and ("@" in value or "." not in value):
        raise ValueError("a domain rule needs a company domain such as example.test")
    if match_type == "domain" and value in PUBLIC_MAIL_DOMAINS:
        raise ValueError("a public mail domain does not identify a contractor; route an exact address instead")
    if not (contractor_name or "").strip() and not (department or "").strip():
        raise ValueError("a rule sets a contractor, a department, or both")
    with connect() as conn:
        conn.execute(
            "INSERT INTO query_routing_rules(id,match_type,match_value,contractor_name,department,created_by,created_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(match_type,match_value) DO UPDATE SET "
            "contractor_name=excluded.contractor_name,department=excluded.department",
            (
                str(uuid.uuid4()), match_type, value,
                (contractor_name or "").strip() or None, (department or "").strip() or None,
                actor_user_id, now(),
            ),
        )
    return list_routing_rules()


def delete_routing_rule(rule_id: str, is_admin: bool) -> list[dict[str, Any]]:
    if not is_admin:
        raise PermissionError("an administrator is required to change routing rules")
    with connect() as conn:
        conn.execute("DELETE FROM query_routing_rules WHERE id=?", (rule_id,))
    return list_routing_rules()
