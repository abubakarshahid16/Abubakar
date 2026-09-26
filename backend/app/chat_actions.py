"""What a reader does WITH a chat answer: rate it, and file a drafted comment.

OWNER ORDER 2026-09-26 (chat redesign PR 5, section 2g). Two actions, both
the reader's own and both local:

  * FEEDBACK - "Was this right? Yes / No", one per reader per answer, replaced
    when they change their mind. Stored on this machine, never sent anywhere.
  * FILE A COMMENT - "Add to comment sheet". A drafted comment (an ACTION
    answer, `chat_presentation.draft`) becomes a review finding on the
    submittal the answer drew on, in that submittal's latest review run, so
    it prints on the run's comment sheet as the engineer's own row.

THE MODEL NEVER FILES ANYTHING. A draft exists only as text on screen; a
finding exists only after a person presses the button, and the text filed is
the text they had in front of them (edited or not), recorded against their
name. That is why the finding is created CONFIRMED BY THE FILER: they wrote
or approved every word, and a re-run of the comparison - which deletes every
unconfirmed finding in the run - must not erase it.

UNDO IS NARROW ON PURPOSE. Only the person who filed it, only within
`UNDO_SECONDS`, and only while nobody has touched the finding since (its
event history is still just "created"). Past that, it is an ordinary finding
and is changed the ordinary way. An undone finding is removed - from the
sheet and from the findings, with its own history - and the record that it
was filed and withdrawn stays on the link row (`filed_at`, `withdrawn_at`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import review as review_mod
from . import submittal_review
from .db import connect

UNDO_SECONDS = 300
MAX_COMMENT = 8000

_SUBMITTAL = "CONTRACTOR_SUBMITTAL"


class NotFound(LookupError):
    """No such answer in this conversation, or nothing of it may be filed."""


class NothingToFile(ValueError):
    """The answer carries no draft, or no readable document to file it on."""


class UndoClosed(ValueError):
    """Past the undo window, not the filer's, or already changed by someone."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _assistant(conversation_id: str, message_id: str) -> dict:
    row = connect().execute(
        "SELECT id, role, payload, ordinal FROM messages WHERE id = ? AND conversation_id = ?",
        (message_id, conversation_id)).fetchone()
    if row is None or row["role"] != "assistant":
        raise NotFound(message_id)
    try:
        payload = json.loads(row["payload"] or "{}") or {}
    except (TypeError, ValueError):
        payload = {}
    return {"id": row["id"], "ordinal": row["ordinal"], "payload": payload}


# ------------------------------------------------------------------ feedback

def set_feedback(conversation_id: str, message_id: str, *, user_key: str,
                 helpful: bool, note: str | None = None) -> dict:
    _assistant(conversation_id, message_id)
    now = _iso(_now())
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO chat_feedback (message_id, user_key, helpful, note, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(message_id, user_key) DO UPDATE SET
                 helpful = excluded.helpful, note = excluded.note,
                 created_at = excluded.created_at""",
            (message_id, user_key, 1 if helpful else 0, (note or "").strip() or None, now))
    return {"message_id": message_id, "helpful": helpful, "note": (note or "").strip() or None}


def feedback_for(message_ids: list[str], *, user_key: str) -> dict[str, bool]:
    if not message_ids:
        return {}
    marks = ",".join("?" * len(message_ids))
    rows = connect().execute(
        f"SELECT message_id, helpful FROM chat_feedback WHERE user_key = ? AND message_id IN ({marks})",
        [user_key, *message_ids]).fetchall()
    return {r["message_id"]: bool(r["helpful"]) for r in rows}


# ------------------------------------------------------------ filed comments

def _target_document(source_ids: list[str], allowed: frozenset[str]) -> str | None:
    """The document the comment is ABOUT: the submittal among the answer's
    sources when there is one, else the first readable source. Never a
    document the caller may not read."""
    readable = [d for d in dict.fromkeys(source_ids) if d in allowed]
    if not readable:
        return None
    marks = ",".join("?" * len(readable))
    roles = {r["document_id"]: r["document_role"] for r in connect().execute(
        f"SELECT document_id, document_role FROM document_classification WHERE document_id IN ({marks})",
        readable).fetchall()}
    for d in readable:
        if roles.get(d) == _SUBMITTAL:
            return d
    return readable[0]


def _asked_before(conversation_id: str, ordinal: int) -> str:
    row = connect().execute(
        """SELECT text, resolved_question FROM messages
           WHERE conversation_id = ? AND role = 'user' AND ordinal < ?
           ORDER BY ordinal DESC LIMIT 1""", (conversation_id, ordinal)).fetchone()
    return ((row["text"] or row["resolved_question"]) if row else "") or ""


def _document_name(document_id: str) -> str:
    row = connect().execute(
        """SELECT d.filename, c.title FROM documents d
           LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?""",
        (document_id,)).fetchone()
    if row is None:
        return "the document"
    return (row["title"] or "").strip() or row["filename"]


def file_comment(conversation_id: str, message_id: str, *, text: str,
                 user_id: str | None, allowed_document_ids: frozenset[str]) -> dict:
    """File a drafted comment as a finding. Returns where it went."""
    message = _assistant(conversation_id, message_id)
    draft = message["payload"].get("draft")
    if not isinstance(draft, dict) or draft.get("type") != "comment":
        raise NothingToFile("this answer is not a drafted comment")
    body = (text or "").strip()
    if not body:
        raise NothingToFile("the comment is empty")
    if len(body) > MAX_COMMENT:
        raise NothingToFile(f"the comment is longer than {MAX_COMMENT} characters")
    document_id = _target_document(list(draft.get("source_ids") or []), allowed_document_ids)
    if document_id is None:
        raise NothingToFile("this comment names no document you can file it on")

    runs = submittal_review.list_review_runs(
        allowed_document_ids=allowed_document_ids, submittal_document_id=document_id)
    run_id = runs[0]["id"] if runs else None
    asked = _asked_before(conversation_id, message["ordinal"])
    now = _now()
    finding = review_mod.create({
        "document_id": document_id,
        "category": "technical_query",
        "severity": "minor",
        "requirement": (f"Raised from chat: {asked}" if asked else "Raised from chat")[:4000],
        "finding": body,
        "required_action": "Contractor to respond to this comment.",
        "status": "open",
        "approval_status": "pending",
    }, created_by=user_id)
    conn = connect()
    with conn:
        conn.execute(
            """UPDATE review_findings SET review_run_id = ?, origin = 'chat',
                   confirmed_by = ?, confirmed_at = ? WHERE id = ?""",
            (run_id, user_id or "", _iso(now), finding["id"]))
        conn.execute(
            """INSERT INTO chat_filed_comments
               (message_id, finding_id, document_id, filed_by, filed_at) VALUES (?, ?, ?, ?, ?)""",
            (message_id, finding["id"], document_id, user_id, _iso(now)))
    on_sheet = 0
    if run_id:
        on_sheet = connect().execute(
            "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ? AND origin = 'chat'",
            (run_id,)).fetchone()[0]
    return {
        "finding_id": finding["id"],
        "message_id": message_id,
        "document_id": document_id,
        "document_name": _document_name(document_id),
        "review_run_id": run_id,
        "chat_comments_on_sheet": on_sheet,
        "undo_until": _iso(now + timedelta(seconds=UNDO_SECONDS)),
    }


def withdraw_comment(conversation_id: str, message_id: str, finding_id: str, *,
                     user_id: str | None) -> dict:
    """Undo a filing: the filer, inside the window, and only if untouched."""
    _assistant(conversation_id, message_id)
    conn = connect()
    link = conn.execute(
        "SELECT * FROM chat_filed_comments WHERE message_id = ? AND finding_id = ?",
        (message_id, finding_id)).fetchone()
    if link is None or link["withdrawn_at"]:
        raise NotFound(finding_id)
    if (link["filed_by"] or None) != (user_id or None):
        raise UndoClosed("only the person who filed a comment can undo it")
    filed = datetime.fromisoformat(link["filed_at"].replace("Z", "+00:00"))
    if _now() - filed > timedelta(seconds=UNDO_SECONDS):
        raise UndoClosed("the undo window has closed; change the finding on the review instead")
    events = [e["event_type"] for e in review_mod.history(finding_id)]
    if events != ["created"]:
        raise UndoClosed("the finding has been changed since it was filed; change it on the review")
    now = _iso(_now())
    with conn:
        # The finding's own events go with it (ON DELETE CASCADE). The fact
        # that it was filed and then withdrawn stays on the link row, which
        # has no foreign key to the finding for exactly this reason.
        conn.execute("DELETE FROM review_findings WHERE id = ?", (finding_id,))
        conn.execute(
            "UPDATE chat_filed_comments SET withdrawn_at = ? WHERE message_id = ? AND finding_id = ?",
            (now, message_id, finding_id))
    return {"finding_id": finding_id, "withdrawn": True}


def filed_for(message_ids: list[str]) -> dict[str, dict]:
    """The live (not withdrawn) filing for each message, if any."""
    if not message_ids:
        return {}
    marks = ",".join("?" * len(message_ids))
    rows = connect().execute(
        f"""SELECT message_id, finding_id, document_id, filed_at FROM chat_filed_comments
            WHERE withdrawn_at IS NULL AND message_id IN ({marks})
            ORDER BY filed_at""", message_ids).fetchall()
    return {r["message_id"]: {"finding_id": r["finding_id"], "document_id": r["document_id"],
                              "filed_at": r["filed_at"]} for r in rows}
