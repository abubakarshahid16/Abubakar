"""The engineer's decision on every POINT of a review, and the points an engineer adds (owner, 12 Nov 2026, the redesigned review page).

KEEP, EDIT, REMOVE, for the rule check's comments AND the AI review's lines alike.
  * Keep   the point stands as the reviewer wrote it.
  * Edit   the engineer's text replaces the comment on the sheets; the original text is KEPT in the record (`original`).
  * Remove a one-line reason is REQUIRED; the point stays in the internal record (never a silent delete) and leaves the CRS sheets.
Who and when are the caller and the clock; every decision is an audit event and a row of its own: nothing is overwritten (the latest
row of a point wins, the earlier ones stay). A point's id names its run (`rc:<finding>`, `ai:<run>:<item>`), so a new review's points
start undecided; a decision is never carried to a point it was not made on.

ADD A POINT: the engineer's own comment (text required; page, rule book and clause optional). It is "Added by <name>", decided by
definition, and goes on the CRS sheets like a kept point with Comment By = the engineer, never "AI".

The rule check keeps its own decision record too (`crs_issue`, Keep = accept, Remove = reject): `apply_to_rows` and the route write
THROUGH to it so the older screens and the issue gate read the same answer.

Words and ids only in the audit; the engineer's own text is stored in this table and nowhere else. Opens no socket.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from .db import connect

KEEP, EDIT, REMOVE = "keep", "edit", "remove"
STATES = (KEEP, EDIT, REMOVE)
STATE_WORDS = {KEEP: "Kept", EDIT: "Edited", REMOVE: "Removed"}
AUDIT = "review_point_decided"
AUDIT_ADDED = "review_point_added"
MAX_TEXT = 4000
#: The same minimum as the rule check's own record (`crs_issue.MIN_REASON_LENGTH`): one reason, two records.
MIN_REASON = 10


class PointRefused(ValueError):
    """A decision or an added point that cannot be recorded; the message is a plain sentence."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_point_decision (
            id TEXT PRIMARY KEY,
            paper_document_id TEXT NOT NULL,
            point_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('keep', 'edit', 'remove')),
            text TEXT,
            original TEXT,
            reason TEXT,
            decided_by TEXT NOT NULL,
            decided_at TEXT NOT NULL)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS review_point_decision_paper ON review_point_decision (paper_document_id, point_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_point_added (
            id TEXT PRIMARY KEY,
            paper_document_id TEXT NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            rule_book TEXT,
            clause TEXT,
            added_by TEXT NOT NULL,
            added_at TEXT NOT NULL)"""
    )


def _has(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'review_point_decision'"
        ).fetchone()
        is not None
    )


def _audit(conn, action: str, actor: str, paper: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (at, actor_user_id, actor_username, action, resource_type, resource_id, outcome, detail)"
        " VALUES (?, NULL, ?, ?, 'document', ?, 'ok', ?)",
        (_now(), actor, action, paper, json.dumps(detail, sort_keys=True)),
    )


def check(state: str, text: str | None, reason: str | None) -> tuple[str, str]:
    """Validate one decision; returns (text, reason) cleaned. Raises `PointRefused`."""
    if state not in STATES:
        raise PointRefused("a point is kept, edited or removed")
    text, reason = (text or "").strip(), " ".join((reason or "").split())
    if state == EDIT and not text:
        raise PointRefused("an edited point needs the engineer's text")
    if state == REMOVE and len(reason) < MIN_REASON:
        raise PointRefused("a removed point needs a one-line reason")
    if len(text) > MAX_TEXT or len(reason) > 300:
        raise PointRefused("the text or the reason is too long")
    return text, reason


def insert_row(
    conn,
    paper_id: str,
    point_id: str,
    state: str,
    *,
    actor: str,
    text: str,
    reason: str,
    original: str | None,
) -> dict:
    """INSERT one decision (and its audit event) on `conn` WITHOUT committing, and without making the tables: the caller did, so this
    can sit in the same transaction as another record."""
    row = {
        "id": str(uuid.uuid4()),
        "paper_document_id": paper_id,
        "point_id": point_id,
        "state": state,
        "text": text or None,
        "original": ((original or "").strip() or None) if state == EDIT else None,
        "reason": reason or None,
        "decided_by": actor,
        "decided_at": _now(),
    }
    conn.execute(
        "INSERT INTO review_point_decision (id, paper_document_id, point_id, state, text, original, reason, decided_by, decided_at)"
        " VALUES (:id, :paper_document_id, :point_id, :state, :text, :original, :reason, :decided_by, :decided_at)",
        row,
    )
    _audit(conn, AUDIT, actor, paper_id, {"point": point_id, "state": state})
    return row


def decide(
    paper_id: str,
    point_id: str,
    state: str,
    *,
    actor: str,
    text: str | None = None,
    reason: str | None = None,
    original: str | None = None,
) -> dict:
    """Record one decision of an AI line (a rule-check point goes through `review_point_sync`, which writes both records in one
    transaction). Raises `PointRefused` for an unknown state, an edit with no text, a removal with no reason (or one of more than one
    line), or text too long."""
    text, reason = check(state, text, reason)
    conn = connect()
    ensure_schema(conn)
    with conn:
        return insert_row(
            conn,
            paper_id,
            point_id,
            state,
            actor=actor,
            text=text,
            reason=reason,
            original=original,
        )


def latest(paper_id: str) -> dict[str, dict]:
    """{point id: its latest decision} for this paper. Nothing recorded (or no table yet): {}."""
    conn = connect()
    if not _has(conn):
        return {}
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT * FROM review_point_decision WHERE paper_document_id = ? ORDER BY rowid",
        (paper_id,),  # commit order, not the clock
    ):
        out[r["point_id"]] = dict(r)
    return out


def people(paper_id: str) -> set[str]:
    """The user ids behind this paper's decisions and added points (to print their display names)."""
    return {d["decided_by"] for d in latest(paper_id).values()} | {
        r["added_by"] for r in added(paper_id)
    }


def history(paper_id: str, point_id: str) -> list[dict]:
    conn = connect()
    if not _has(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM review_point_decision WHERE paper_document_id = ? AND point_id = ? ORDER BY decided_at DESC, rowid DESC",
            (paper_id, point_id),
        )
    ]


def add_point(
    paper_id: str,
    text: str,
    *,
    actor: str,
    page: int | None = None,
    rule_book: str | None = None,
    clause: str | None = None,
) -> dict:
    """The engineer's own comment as a new point. Text is required; page, rule book and clause are optional."""
    text = (text or "").strip()
    if not text:
        raise PointRefused("a point needs the engineer's text")
    if len(text) > MAX_TEXT:
        raise PointRefused("the text is too long")
    if page is not None and (
        not isinstance(page, int) or isinstance(page, bool) or page < 1
    ):
        raise PointRefused("the page must be a page number")
    conn = connect()
    ensure_schema(conn)
    row = {
        "id": str(uuid.uuid4()),
        "paper_document_id": paper_id,
        "text": text,
        "page": page,
        "rule_book": (rule_book or "").strip() or None,
        "clause": (clause or "").strip() or None,
        "added_by": actor,
        "added_at": _now(),
    }
    with conn:
        conn.execute(
            "INSERT INTO review_point_added (id, paper_document_id, text, page, rule_book, clause, added_by, added_at)"
            " VALUES (:id, :paper_document_id, :text, :page, :rule_book, :clause, :added_by, :added_at)",
            row,
        )
        _audit(conn, AUDIT_ADDED, actor, paper_id, {"point": f"add:{row['id']}"})
    return row


def added(paper_id: str) -> list[dict]:
    conn = connect()
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'review_point_added'"
        ).fetchone()
        is None
    ):
        return []
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM review_point_added WHERE paper_document_id = ? ORDER BY added_at, rowid",
            (paper_id,),
        )
    ]


def added_point(row: dict, who: str) -> dict:
    """An added point in the list's shape. Rank 4 (it is the engineer's own question or comment), decided by definition."""
    from . import review_points as rp

    return {
        "id": f"add:{row['id']}",
        "source": rp.SOURCE_ADDED,
        "source_words": rp.SOURCE_WORDS[rp.SOURCE_ADDED],
        "engine": None,
        "rank": 4,
        "tile": "questions",
        "firm": None,
        "other_kind": None,
        "name": " ".join(row["text"].split()[:8]),
        "page": row["page"],
        "rule_book": row["rule_book"],
        "clause": row["clause"],
        "action": row["text"],
        "paper_quote": None,
        "clause_quote": None,
        "paper_quote_note": rp.NO_PAPER_QUOTE,
        "clause_quote_note": rp.NO_CLAUSE_QUOTE,
        "route_note": None,
        "view_page": None,
        "shall": True,
        "group_key": None,
        "added_by": who,
        "added_at": row["added_at"],
    }


# --------------------------------------------------------------------------------------------- what the sheets hold

REMOVED_BY_DECISION = "removed by the engineer"


def decision_of_point(point_id: str, decisions: dict[str, dict]) -> dict:
    """The decision state of one point as the list shows it: {state, by, at, text, reason}. Added points are kept by definition."""
    if point_id.startswith("add:"):
        return {"state": KEEP, "by": None, "at": None, "words": "Added"}
    d = decisions.get(point_id)
    if not d:
        return {"state": None, "words": "Not decided"}
    return {
        "state": d["state"],
        "by": d["decided_by"],
        "at": d["decided_at"],
        "text": d["text"],
        "reason": d["reason"],
        "words": STATE_WORDS[d["state"]],
    }


def apply_to_rows(
    paper_id: str, rows: list[dict], names: dict[str, str] | None = None
) -> None:
    """Make the RULE CHECK's CRS rows hold exactly what the engineer decided (both copies): a removed point's row leaves the sheet, an
    edited point's text replaces the comment (Comment By = Edited by the engineer), a kept one is confirmed, and each added point is a
    kept row with the engineer as its author. In place; nothing when no decision and no added point exist."""
    from .crs_mapping import ROW_KIND_ENGINEER_COMMENT

    decisions = latest(paper_id)
    extra = added(paper_id)
    if not decisions and not extra:
        return
    names = names or {}
    keep_rows = []
    for row in rows:
        key = str(row.get("finding_id") or row.get("crs_row_key") or "")
        d = decisions.get(f"rc:{key}") if key else None
        if d and d["state"] == REMOVE:
            continue
        if d and d["state"] == EDIT and d["text"]:
            who = names.get(d["decided_by"]) or d["decided_by"]
            row.update(
                comment=d["text"],
                comment_by=f"Edited by {who}",
                engineer_confirmed=True,
                edited=True,
                engineer_worded=True,
            )
        elif d and d["state"] == KEEP:
            row["engineer_confirmed"] = True
        keep_rows.append(row)
    rows[:] = keep_rows
    for r in extra:
        who = names.get(r["added_by"]) or r["added_by"]
        rows.append(
            {
                "finding_id": "",
                "document_name": rows[0].get("document_name", "") if rows else "",
                "page_section": f"Page {r['page']}" if r["page"] else "",
                "comment": r["text"],
                "comment_by": f"Engineer: {who}",
                "standard_reference": " ".join(
                    x
                    for x in (
                        r["rule_book"],
                        f"clause {r['clause']}" if r["clause"] else "",
                    )
                    if x
                ),
                "row_kind": ROW_KIND_ENGINEER_COMMENT,
                "engineer_confirmed": True,
                "crs_row_key": f"add:{r['id']}",
            }
        )


def apply_to_lines(
    paper_id: str, run_id: str, lines: list[dict], names: dict[str, str] | None = None
) -> list[dict]:
    """The AI review's stored lines as its CRS sheets must hold them: removed lines out, an edited line carries `engineer_text` and
    `engineer_by` (the sheet prints them as the comment and its author), each added point a kept Query line by the engineer."""
    decisions = latest(paper_id)
    names = names or {}
    out = []
    for ln in lines:
        d = decisions.get(f"ai:{run_id}:{ln.get('item_id')}")
        if d and d["state"] == REMOVE:
            continue
        if d and d["state"] == EDIT and d["text"]:
            ln = {
                **ln,
                "engineer_text": d["text"],
                "engineer_by": names.get(d["decided_by"]) or d["decided_by"],
            }
        out.append(ln)
    for r in added(paper_id):
        out.append(
            {
                "item_id": f"add:{r['id']}",
                "verdict_class": "Query for the engineer",
                "word": "Query",
                "paper_page": r["page"],
                "standard": r["rule_book"] or "",
                "clause": r["clause"] or "",
                "engineer_text": r["text"],
                "engineer_by": names.get(r["added_by"]) or r["added_by"],
                "engineer_added": True,
            }
        )
    return out
