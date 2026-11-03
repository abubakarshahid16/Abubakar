"""#805 STEP 5: the rulebook's BOOK VERSIONS, and restoring any one of them in one step.

A BOOK VERSION is one state of the whole rulebook: a snapshot (`rulebook_snapshot`) whose member list differs from the
one before it. Numbered 1, 2, 3 ... in the order they were taken; a compile that changed nothing makes no new number, and
a review run's own snapshot is not a change to the book, so it takes none. `books` lists them. Nothing is stored for the
number: it is read from the append-only snapshots, so it cannot drift.

RESTORING IS AN APPEND, NEVER AN ERASE. The tables refuse UPDATE and DELETE, so a restore writes a new snapshot with the
old book's members and a `rulebook_restore` row that says who, when, why and which book. It first VERIFIES the old book:
its hash is recomputed from its members and must equal the hash stored when it was taken, or nothing is written. After a
restore the book is PINNED: `current_filter` makes `rulebook_v2` serve exactly the versions that were in force in that
book (a rule changed since is read at its old version; a rule added since is not served and a review sends it to the
engineer). A pin only ever narrows what is served to what a person had approved in that book. `release_pin` (also a
logged row) returns to the newest versions.

A COPY ONLY. Needs RULEBOOK_V2_ENABLED and the tables, refuses a live-shaped file (`RefusedLive`), and never calls
`live_guard.prepare_live_write`: the live database is written only by the app. Reads nothing from a document.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from . import live_guard

#: Snapshots a review run takes of its own (`rulebook_v2_review`): not a change to the book.
REVIEW_SNAPSHOT = "review_run"
RESTORE_SNAPSHOT = "restore"
_NEWEST = "v.version_no = (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
_PINNED = "v.id IN (SELECT rule_version_id FROM rulebook_snapshot_rule WHERE snapshot_id = '{}' AND approval_id IS NOT NULL)"


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _members(conn, snapshot_id: str) -> list[list]:
    """[rule key, version number, content hash, approval id or ""] for each member, in the order the hash was taken."""
    return [
        [r[0], r[1], r[2], r[3] or ""]
        for r in conn.execute(
            "SELECT r.rule_key, v.version_no, v.content_hash, s.approval_id FROM rulebook_snapshot_rule s"
            " JOIN rulebook_version v ON v.id = s.rule_version_id JOIN rulebook_rule r ON r.id = v.rule_id"
            " WHERE s.snapshot_id = ? ORDER BY r.rule_key",
            (snapshot_id,),
        )
    ]


def hash_of(conn, snapshot_id: str) -> str:
    """The hash `rulebook_v2.take_snapshot` computes, recomputed from the members now."""
    return hashlib.sha256(
        json.dumps(_members(conn, snapshot_id)).encode("utf-8")
    ).hexdigest()


def books(conn) -> list[dict]:
    """Every book version, oldest first: {book_no, snapshot_id, hash, taken_at, rules_total, rules_in_force,
    restored_from_book}. No tables: none."""
    if not _has(conn, "rulebook_snapshot"):
        return []
    restored = {}
    if _has(conn, "rulebook_restore"):
        restored = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT snapshot_id, restored_book_no FROM rulebook_restore WHERE snapshot_id IS NOT NULL"
            )
        }
    out: list[dict] = []
    for row in conn.execute(
        "SELECT id, snapshot_hash, created_at, rules_total, rules_in_force FROM rulebook_snapshot"
        " WHERE standard_document_id <> ? ORDER BY rowid",
        (REVIEW_SNAPSHOT,),
    ):
        if out and out[-1]["hash"] == row[1]:
            continue
        out.append(
            {
                "book_no": len(out) + 1,
                "snapshot_id": row[0],
                "hash": row[1],
                "taken_at": row[2],
                "rules_total": row[3],
                "rules_in_force": row[4],
                "restored_from_book": restored.get(row[0]),
            }
        )
    return out


def mark_change(conn, actor: str, kind: str) -> str:
    """Take a snapshot for a change a compile does not make (a batch of approvals), inside the caller's transaction,
    so the book version list sees it. Returns the snapshot id. The kind is the snapshot's document column, never
    `review_run`: a review's own snapshot is not a change."""
    from . import rulebook_v2

    rulebook_v2.require_on()
    if kind in (REVIEW_SNAPSHOT, ""):
        raise rulebook_v2.RuleRefused("a change names its kind")
    return rulebook_v2.take_snapshot(conn, f"{kind}:{uuid.uuid4().hex}", kind, {kind: 1}, actor)


def active_pin(conn) -> str | None:
    """The snapshot a restore pinned the book to, or None (never restored, or released). Reads only."""
    if not _has(conn, "rulebook_restore"):
        return None
    row = conn.execute(
        "SELECT snapshot_id FROM rulebook_restore ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def current_filter(conn) -> str:
    """SQL on `rulebook_version v`: the newest version of each rule, or, while a restore is pinned, the versions that
    were in force in that book. One place both the served rules and a run's snapshot read it. The pin is one of our own
    ids (32 hex characters), checked before it is written into the statement."""
    pin = active_pin(conn)
    if pin is None:
        return _NEWEST
    if not re.fullmatch(r"[0-9a-f]{32}", pin):
        raise ValueError("a restore record holds an id that is not one of ours")
    return _PINNED.format(pin)


def _gate(conn):
    from . import rulebook_v2

    rulebook_v2.require_on()
    if not rulebook_v2.has_schema(conn):
        raise rulebook_v2.RuleRefused("the rulebook tables are not on this database")
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise rulebook_v2.RefusedLive(
            "this is a live-shaped database; restore on a copy"
        )
    if not _has(conn, "rulebook_restore"):
        raise rulebook_v2.RuleRefused(
            "run ensure_schema on this copy first: the restore table is missing"
        )
    return rulebook_v2


def _write(conn, **row) -> None:
    conn.execute(
        "INSERT INTO rulebook_restore (id, action, snapshot_id, source_snapshot_id, book_no, restored_book_no,"
        " source_hash, reason, actor, at) VALUES (:id,:action,:snapshot_id,:source_snapshot_id,:book_no,"
        ":restored_book_no,:source_hash,:reason,:actor,:at)",
        {
            "snapshot_id": None,
            "source_snapshot_id": None,
            "book_no": None,
            "restored_book_no": None,
            "source_hash": None,
            "id": uuid.uuid4().hex,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            **row,
        },
    )


def restore_book(conn, book_no: int, actor: str, reason: str) -> dict:
    """Pin the rulebook to book version `book_no`, in one step: verify it, append a snapshot of its members and a
    restore record, and verify the copy. Refuses (writes nothing) for an unknown number, a book whose hash does not
    match its members, a blank actor or reason, a live-shaped file, or the switch off."""
    rulebook_v2 = _gate(conn)
    if not (actor or "").strip() or not (reason or "").strip():
        raise rulebook_v2.RuleRefused("a restore names who does it and why")
    wanted = next((b for b in books(conn) if b["book_no"] == book_no), None)
    if wanted is None:
        raise rulebook_v2.RuleRefused(f"there is no book version {book_no}")
    if hash_of(conn, wanted["snapshot_id"]) != wanted["hash"]:
        raise rulebook_v2.RuleRefused(
            f"book version {book_no} does not verify: its members no longer match its hash"
        )
    new_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO rulebook_snapshot (id, compile_run_id, standard_document_id, snapshot_hash, rules_total,"
            " rules_in_force, counts_json, created_by, created_at, standard)"
            " SELECT ?, ?, ?, snapshot_hash, rules_total, rules_in_force, ?, ?, ?, standard FROM rulebook_snapshot"
            " WHERE id = ?",
            (
                new_id,
                f"restore:{new_id}",
                RESTORE_SNAPSHOT,
                json.dumps({"restored_book": book_no}),
                actor,
                datetime.now(UTC).isoformat(timespec="seconds"),
                wanted["snapshot_id"],
            ),
        )
        conn.execute(
            "INSERT INTO rulebook_snapshot_rule (snapshot_id, rule_version_id, approval_id)"
            " SELECT ?, rule_version_id, approval_id FROM rulebook_snapshot_rule WHERE snapshot_id = ?",
            (new_id, wanted["snapshot_id"]),
        )
        if hash_of(conn, new_id) != wanted["hash"]:
            raise rulebook_v2.RuleRefused(
                "the restored copy does not match the book; nothing was written"
            )
        _write(
            conn,
            action="restore",
            snapshot_id=new_id,
            source_snapshot_id=wanted["snapshot_id"],
            book_no=len(books(conn)),
            restored_book_no=book_no,
            source_hash=wanted["hash"],
            reason=reason.strip(),
            actor=actor.strip(),
        )
    return {
        "restored_book": book_no,
        "new_book_no": len(books(conn)),
        "snapshot_id": new_id,
        "hash": wanted["hash"],
    }


def release_pin(conn, actor: str, reason: str) -> dict:
    """Return to the newest version of every rule. Logged like a restore. Nothing pinned: refused, nothing written."""
    rulebook_v2 = _gate(conn)
    if not (actor or "").strip() or not (reason or "").strip():
        raise rulebook_v2.RuleRefused("releasing a restore names who does it and why")
    if active_pin(conn) is None:
        raise rulebook_v2.RuleRefused("no restore is pinned")
    with conn:
        _write(conn, action="release", reason=reason.strip(), actor=actor.strip())
    return {"released": True}
