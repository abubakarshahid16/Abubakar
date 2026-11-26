"""The company's OWN replies in a technical-query thread (lead-4, 26 Nov 2026, after the owner's first import: 41 of 77 listed messages
were our own replies and were skipped, losing the answer history).

An own reply (sent from the connected mailbox) is ATTACHED to the query it answers, marked "sent by us" (`is_inbound` = 0). It never
creates a query and never counts as a new TQ or CFC. The query is found the way a contractor's follow-up is: the full TQ / CFC number
in the subject (in the same mailbox), else the Gmail thread (in the same mailbox). When neither is held yet the reply is not stored and
the import counts it apart. Its attachments are not stored (our own papers are not query evidence). The query's status does not change.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .db import connect

#: The import job's reasons for an own reply (`gmail_import_jobs`): kept with the query, or no query of it held yet.
ATTACHED = "our replies, added to their query (sent by us)"
NO_QUERY = "sent from this mailbox, with no query of its thread or number yet"
#: A message read again ("Import the label again") that is already stored: nothing is added, never a second query.
ALREADY = "already stored, nothing added"


def held(data: dict[str, Any]) -> bool:
    """True when this provider message is already stored (on any query of the mailbox)."""
    with connect() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_message_id=?",
                (
                    data["provider"],
                    data.get("mailbox_id") or "",
                    data["provider_message_id"],
                ),
            ).fetchone()
            is not None
        )


def _target(conn, data: dict[str, Any]) -> str | None:
    from . import technical_query_subject

    mailbox_id = data.get("mailbox_id") or ""
    ref = technical_query_subject.parse(data.get("subject"))
    if ref and ref["prefixed"]:
        same = conn.execute(
            "SELECT q.id FROM technical_queries q WHERE q.ref_key=? AND EXISTS (SELECT 1 FROM query_messages m WHERE m.query_id=q.id"
            " AND m.mailbox_id IS ?) ORDER BY q.created_at LIMIT 1",
            (ref["reference"], mailbox_id),
        ).fetchone()
        if same:
            return same["id"]
    thread = data.get("provider_thread_id")
    if thread:
        row = conn.execute(
            "SELECT query_id FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_thread_id=? ORDER BY received_at LIMIT 1",
            (data["provider"], mailbox_id, thread),
        ).fetchone()
        if row:
            return row["query_id"]
    return None


def attach(data: dict[str, Any], actor_user_id: str | None, raw=None) -> str | None:
    """Store our own reply on the query it belongs to, marked sent by us; the query's id, or None when no query of it is held (nothing is
    stored). Importing the same reply again stores nothing new. `raw` (optional) is called only when the reply is kept, and gives its
    stored original email (hash, storage reference)."""
    from .technical_queries import _event, now

    with connect() as conn:
        held = conn.execute(
            "SELECT query_id FROM query_messages WHERE provider=? AND mailbox_id IS ? AND provider_message_id=?",
            (
                data["provider"],
                data.get("mailbox_id") or "",
                data["provider_message_id"],
            ),
        ).fetchone()
        if held:
            return held["query_id"]
        query_id = _target(conn, data)
        if query_id is None:
            return None
        mid = str(uuid.uuid4())
        if raw is not None:
            data = {
                **data,
                **dict(
                    zip(("raw_message_hash", "raw_storage_ref"), raw(), strict=True)
                ),
            }
        conn.execute(
            "INSERT INTO query_messages(id,query_id,provider,mailbox_id,provider_message_id,provider_thread_id,internet_message_id,"
            "from_address,to_addresses,cc_addresses,subject,body,sent_at,received_at,raw_message_hash,raw_storage_ref,is_inbound,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
            (
                mid, query_id, data["provider"], data.get("mailbox_id") or "", data["provider_message_id"], data.get("provider_thread_id"),
                data.get("internet_message_id"), data["from_address"], json.dumps(data.get("to_addresses", [])),
                json.dumps(data.get("cc_addresses", [])), data["subject"], data["body"], data.get("sent_at"),
                data.get("received_at") or now(), data.get("raw_message_hash"), data.get("raw_storage_ref"), now(),
            ),
        )  # fmt: skip
        _event(
            conn,
            query_id,
            "reply_sent_by_us",
            actor_user_id,
            "our own reply in the thread, kept with the query",
        )
    return query_id
