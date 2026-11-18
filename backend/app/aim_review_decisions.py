"""The engineer's decision on each comment of a general review (order 14, owner: "the engineer's sign-off is part of DONE").

ACCEPT, EDIT, REJECT, per comment and per confirmation:
  * accept  the comment stands as the AI wrote it.
  * edit    the engineer's own text; the original stays in the run's own lines (it is not copied here: it was shown to the deciding
            engineer unmasked, and a copy would be served to readers who may not open that book).
  * reject  a one-line reason (at least `MIN_REASON` characters) is required; the comment stays in the record and in the team file.
APPEND-ONLY: every decision is a row of its own and an audit event; nothing is overwritten or deleted. The LATEST row of a comment is its
decision, the earlier rows stay (`revisions` counts them). Who and when are the caller and the clock, never the request.

A comment is named by the run and the point numbers it covers ("3,7,12"), so a decision is never carried to a different comment (a run
whose grouping changed leaves the comment undecided: said, never guessed). No contractor copy is made here: that follows the sign-off.

Ids, the state and the point numbers only in the audit; the engineer's own text and a reject's reason are stored in the table and
nowhere else. No model, no socket.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from .aim_review_store import DECISIONS

ACCEPT, EDIT, REJECT = "accept", "edit", "reject"
STATES = (ACCEPT, EDIT, REJECT)
WORDS = {ACCEPT: "Accepted", EDIT: "Edited", REJECT: "Rejected"}
AUDIT = "general_comment_decided"
MIN_REASON = 10
MAX_TEXT = 4000


class Refused(ValueError):
    """A decision that cannot be recorded; the message is a plain sentence."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def key_of(comment: dict) -> str:
    """The comment's name inside its run: the point numbers it covers, in order."""
    return ",".join(str(n) for n in (comment.get("lines") or [comment.get("n")]))


def check(state: str, text: str | None, reason: str | None) -> tuple[str, str]:
    """Validate one decision; returns (text, reason) cleaned. Raises `Refused`."""
    if state not in STATES:
        raise Refused("a comment is accepted, edited or rejected")
    text, reason = (text or "").strip(), " ".join((reason or "").split())
    if state == EDIT and not text:
        raise Refused("an edited comment needs the engineer's text")
    if state == REJECT and len(reason) < MIN_REASON:
        raise Refused("a rejected comment needs a one-line reason")
    if len(text) > MAX_TEXT or len(reason) > 300:
        raise Refused("the text or the reason is too long")
    return text, reason


def record(
    conn,
    run_id: str,
    paper_id: str,
    comment: dict,
    part: str,
    state: str,
    *,
    actor: str,
    text: str | None,
    reason: str | None,
) -> dict:
    """INSERT one decision and its audit event on `conn` WITHOUT committing. `part` is "comment" or "confirmation"."""
    text, reason = check(state, text, reason)
    row = {
        "id": str(uuid.uuid4()), "run_id": run_id, "paper_document_id": paper_id, "comment_key": key_of(comment), "part": part,
        "state": state, "text": text or None, "original": None, "reason": reason or None, "decided_by": actor, "decided_at": _now(),
    }  # fmt: skip
    conn.execute(
        f"INSERT INTO {DECISIONS} (id, run_id, paper_document_id, comment_key, part, state, text, original, reason, decided_by, decided_at)"
        " VALUES (:id, :run_id, :paper_document_id, :comment_key, :part, :state, :text, :original, :reason, :decided_by, :decided_at)",
        row,
    )
    audit(
        conn,
        actor,
        AUDIT,
        paper_id,
        {"run": run_id, "comment": row["comment_key"], "part": part, "state": state},
        at=row["decided_at"],
    )
    return row


def audit(
    conn,
    actor_id: str,
    action: str,
    paper_id: str,
    detail: dict,
    *,
    at: str | None = None,
) -> None:
    """One audit event of a general review's write, on `conn` WITHOUT committing: the user's id AND login name filled like every other
    write route (a caller with no user row, which only a test scope is, keeps the id in the name column); `detail` is ids, states, counts and point numbers, never the engineer's words."""
    who = conn.execute("SELECT email FROM users WHERE id = ?", (actor_id,)).fetchone()
    conn.execute(
        "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type, resource_id, outcome, detail)"
        " VALUES (?, ?, ?, ?, 'document', ?, 'ok', ?)",
        (
            at or _now(),
            actor_id if who else None,
            str(who["email"]) if who else actor_id,
            action,
            paper_id,
            json.dumps(detail, sort_keys=True),
        ),
    )


def _has(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (DECISIONS,)
        ).fetchone()
        is not None
    )


def _name(conn, user_id: str) -> str:
    row = conn.execute(
        "SELECT display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return str(row["display_name"]) if row and row["display_name"] else str(user_id)


def words_of(decision: dict | None) -> str | None:
    """One cell of words for the file: "Accepted by Name, 18 Nov 2026" / "Edited by Name: <text>" / "Rejected by Name: <reason>"."""
    if not decision:
        return None
    base = f"{WORDS[decision['state']]} by {decision['by']}, {decision['at'][:10]}"
    if decision["state"] == EDIT:
        return f"{base}: {decision['text']}"
    if decision["state"] == REJECT:
        return f"{base}: {decision['reason']}"
    return base


def attach(conn, run_id: str, comments: list[dict], confirmations: list[dict]) -> None:
    """Put each comment's latest decision on it (`decision`: None when undecided). Read only; a database made before the table has none."""
    rows: dict[tuple[str, str], list] = {}
    if _has(conn):
        for r in conn.execute(
            f"SELECT * FROM {DECISIONS} WHERE run_id = ? ORDER BY decided_at, rowid",
            (run_id,),
        ):
            rows.setdefault((r["part"], r["comment_key"]), []).append(r)
    for part, group in (("comment", comments), ("confirmation", confirmations)):
        for c in group:
            history = rows.get((part, key_of(c)))
            if not history:
                c["decision"] = None
                continue
            last = history[-1]
            c["decision"] = {
                "id": last["id"], "state": last["state"], "words": WORDS[last["state"]], "text": last["text"],
                "reason": last["reason"], "by": _name(conn, last["decided_by"]), "at": last["decided_at"], "revisions": len(history),
            }  # fmt: skip
            c["decision"]["sentence"] = words_of(c["decision"])
