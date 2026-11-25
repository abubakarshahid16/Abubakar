"""The learner (#1912; owner, 25 Nov 2026 23:33 via the planner): what an engineer decided on a comment is remembered by RULE and
PAPER KIND, and the next review of the same kind uses it. Behind `settings.aim_review_learner_enabled` (OFF): off, nothing is
stored and no sheet changes.

STORED (`aim_review_learned`, append-only, ids only): one row per decision and per rule the decided comment rests on: the
decision's id, the rule's key, the paper kind, the run, the comment's point numbers, the state, who and when. The engineer's
own words stay where they are (`aim_review_decisions`, read through the decision id); nothing is copied.

A RULE'S KEY (`rule_key`) is what stays the same from one review to the next: a held book's id and clause; else a named book
and clause; else the saved checklist's key and the item's id (a knowledge item of a reused checklist).

USED, when a later review of the same paper kind builds its page or file (`apply`), for each comment not yet decided in it:
  * REJECTED BEFORE: the latest decision on one of its rules (another review, same kind) is a reject: the comment is still
    raised, never dropped, and its TEAM NOTE says "Rejected before by <role> on <date>". Never the comment text, never the
    contractor copy.
  * EDITED BEFORE: no reject, and an engineer edited a comment resting on EXACTLY the same rules AND the same checks (the same
    saved checklist and item ids: one rule judges several fields): the edited words are the comment's words, and the team note says so and keeps the AI's own words. Never for a comment on a book the viewer may not
    open (the edit may hold that book's words).
No AI generalising: an exact key, the same kind, code only. Read only at build; no model, no socket."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

from .config import settings

TABLE = "aim_review_learned"
REJECT, EDIT = "reject", "edit"
_DDL = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        decision_id TEXT NOT NULL, rule_key TEXT NOT NULL, paper_kind TEXT NOT NULL, run_id TEXT NOT NULL,
        comment_key TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('accept', 'edit', 'reject')),
        decided_by TEXT NOT NULL, decided_at TEXT NOT NULL, learned_at TEXT NOT NULL,
        PRIMARY KEY (decision_id, rule_key))""",
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_rule ON {TABLE} (paper_kind, rule_key, decided_at)",
    *(
        f"""CREATE TRIGGER IF NOT EXISTS {TABLE}_no_{op} BEFORE {op.upper()} ON {TABLE}
            BEGIN SELECT RAISE(ABORT, '{TABLE}: rows are never {op}d'); END"""
        for op in ("update", "delete")
    ),
)
HIDDEN_BOOK_WORDS = "a rule book you may not open"  # the view's own words (`aim_review_view.HIDDEN_BOOK_WORDS`)


def on() -> bool:
    return bool(settings.aim_review_learner_enabled)


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def rule_key(point: dict, checklist_key: str | None) -> str | None:
    """The point's rule, the same from one review to the next; None when it names no rule at all."""
    clause = _norm(point.get("clause"))
    book = str(point.get("book_document_id") or "")
    if book and clause:
        return f"book:{book}#{clause}"
    standard = _norm(point.get("standard"))
    if standard and clause and standard != HIDDEN_BOOK_WORDS:
        return f"named:{standard}#{clause}"
    item = str(point.get("item_id") or "")
    if item and checklist_key:
        return f"item:{checklist_key}#{item}"
    return None


def _kind(run: dict) -> str:
    try:
        identity = json.loads(run.get("identity_json") or "{}")
    except (TypeError, ValueError):
        identity = {}
    return str((identity or {}).get("kind") or "")


def _has(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
        ).fetchone()
        is not None
    )


def _keys_of(numbers, rows: list[dict], checklist_key) -> set[str]:
    """The rule keys of the stored lines at these 1-based positions (a comment's point numbers)."""
    keys = set()
    for n in numbers:
        if 1 <= n <= len(rows) and (k := rule_key(rows[n - 1], checklist_key)):
            keys.add(k)
    return keys


def learn(conn, decision: dict) -> int:
    """Store the rule rows of ONE recorded decision on `conn` WITHOUT committing (switch off: nothing). Idempotent. Returns how
    many rows were added. A run with no kind, or a comment on no rule, adds none."""
    from . import aim_review_store

    if not on():
        return 0
    run = aim_review_store.run(conn, decision["run_id"])
    kind = _kind(run or {})
    if not run or not kind:
        return 0
    numbers = [
        int(x) for x in str(decision["comment_key"]).split(",") if x.strip().isdigit()
    ]
    keys = _keys_of(
        numbers, aim_review_store.lines(conn, run["run_id"]), run.get("checklist_key")
    )
    for statement in _DDL:
        conn.execute(statement)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    added = 0
    for key in sorted(keys):
        cur = conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} (decision_id, rule_key, paper_kind, run_id, comment_key, state, decided_by,"
            " decided_at, learned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision["id"], key, kind, run["run_id"], decision["comment_key"], decision["state"], decision["decided_by"],
             decision["decided_at"], now),
        )  # fmt: skip
        added += cur.rowcount
    return added


def backfill(conn) -> int:
    """Store the rule rows of every decision already recorded (switch on), on `conn`, committing. Idempotent."""
    from .aim_review_store import DECISIONS

    if (
        not on()
        or not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (DECISIONS,)
        ).fetchone()
    ):
        return 0
    added = sum(
        learn(conn, dict(r))
        for r in conn.execute(
            f"SELECT * FROM {DECISIONS} ORDER BY decided_at, rowid"
        ).fetchall()
    )
    conn.commit()
    return added


def _role(conn, user_id: str) -> str:
    """The decider's role names ("engineer", "admin"), never a person's name; "an engineer" when none is recorded."""
    try:
        names = sorted({str(r[0]) for r in conn.execute(
            "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ?", (user_id,))})  # fmt: skip
    except sqlite3.Error:  # a database without the role tables
        names = []
    return " / ".join(names) or "an engineer"


def _latest(conn, kind: str, keys: set[str], run_id: str) -> dict[str, dict]:
    """{rule key: the latest decision on it in ANOTHER review of this kind}."""
    if not keys:
        return {}
    marks = ",".join("?" for _ in keys)
    out: dict[str, dict] = {}
    for r in conn.execute(
        f"SELECT * FROM {TABLE} WHERE paper_kind = ? AND run_id != ? AND rule_key IN ({marks}) ORDER BY decided_at, rowid",
        (kind, run_id, *sorted(keys)),
    ):
        out[r["rule_key"]] = dict(r)
    return out


def _edit_text(conn, decision_id: str) -> str | None:
    from .aim_review_store import DECISIONS

    row = conn.execute(
        f"SELECT state, text FROM {DECISIONS} WHERE id = ?", (decision_id,)
    ).fetchone()
    return str(row["text"]) if row and row["state"] == EDIT and row["text"] else None


def apply(conn, run: dict, comments: list[dict], points: list[dict]) -> int:
    """Mark (in place) each undecided comment of `run` with what was learned on its rules; returns how many comments changed.
    Switch off, no table, no kind: nothing."""
    kind = _kind(run)
    if not on() or not kind or not _has(conn):
        return 0
    by_n = {p["n"]: p for p in points}
    changed = 0
    for c in comments:
        if c.get("decision"):
            continue
        members = [by_n[n] for n in c.get("lines") or [c["n"]] if n in by_n]
        keys = {k for m in members if (k := rule_key(m, run.get("checklist_key")))}
        latest = _latest(conn, kind, keys, run["run_id"])
        rejected = sorted(
            (r for r in latest.values() if r["state"] == REJECT),
            key=lambda r: r["decided_at"],
        )
        learned: dict = {}
        if rejected:
            last = rejected[-1]
            learned = {"rejected_before": {"role": _role(conn, last["decided_by"]), "on": last["decided_at"][:10],
                                           "rules": len(rejected)}}  # fmt: skip
        elif keys and not any(m.get("standard") == HIDDEN_BOOK_WORDS for m in members):
            learned = _reuse(conn, run, c, members, keys, latest)
        if learned:
            c["learned"] = learned
            changed += 1
    return changed


def _reuse(
    conn,
    run: dict,
    c: dict,
    members: list[dict],
    keys: set[str],
    latest: dict[str, dict],
) -> dict:
    """The latest decision on EVERY one of these rules is one and the same edit, of a comment on exactly these rules AND checks
    (another review, this kind, the same saved checklist): its words become the comment's. A later decision on it wins."""
    ids = {r["decision_id"] for r in latest.values()}
    if set(latest) != keys or len(ids) != 1:
        return {}
    last = next(iter(latest.values()))
    total = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE decision_id = ?", (last["decision_id"],)
    ).fetchone()[0]
    text = (
        _edit_text(conn, last["decision_id"])
        if last["state"] == EDIT and total == len(keys)
        else None
    )
    if not text or _check_then(conn, last) != _check(run, members):
        return {}  # one rule judges several checks and fields: an edit written for one is never put on another
    ai_words = c.get("we_ask") or c.get("comment") or ""
    c["comment"], c["we_ask"] = text, text
    return {
        "edited_before": {
            "role": _role(conn, last["decided_by"]),
            "on": last["decided_at"][:10],
            "ai_words": ai_words,
        }
    }


def _check(run: dict, points) -> tuple:
    """(the saved checklist's version, its item ids): the same CHECK, not only the same rule. Item ids hold only inside one saved
    checklist, so a rebuilt checklist never carries an edit across."""
    return str(run.get("checklist_sha256") or ""), frozenset(
        str(p.get("item_id") or "") for p in points
    )


def _check_then(conn, learned_row: dict) -> tuple:
    """The same for the comment the engineer edited, read from its own run and stored lines."""
    from . import aim_review_store

    rows = aim_review_store.lines(conn, learned_row["run_id"])
    numbers = [
        int(x)
        for x in str(learned_row["comment_key"]).split(",")
        if x.strip().isdigit()
    ]
    return _check(
        aim_review_store.run(conn, learned_row["run_id"]) or {},
        (rows[n - 1] for n in numbers if 1 <= n <= len(rows)),
    )


def team_words(learned) -> str | None:
    """The team file's note words for a learned comment (never the comment text, never the contractor copy)."""
    if not isinstance(learned, dict):
        return None
    if r := learned.get("rejected_before"):
        return f"Rejected before by {r['role']} on {r['on']} (the same rule, the same kind of paper)."
    if e := learned.get("edited_before"):
        return (f"Wording reused from an edit by {e['role']} on {e['on']} (the same rule, the same kind of paper). "
                f'The AI\'s own words: "{e["ai_words"]}"')  # fmt: skip
    return None
