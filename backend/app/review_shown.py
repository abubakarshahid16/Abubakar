"""The list a review run was STARTED WITH: the documents the screen showed would leave this computer (owner decision, 12 Nov 2026,
#1584: "the screen lists every document that will leave the Mac before the review starts").

WHAT IT DECIDES. A document with the role SPECIFICATION that is NOT the paper under review (it would go out because the review
cites it, or it governs) is sent only if the run's stored list names it. No list stored for the run (every route today) means no
cited specification is sent. The paper under review and the rule books are not asked here: their own gates stand.
It only NARROWS (CLAUDE.md rule 1 and 5): a document on the list is still subject to every other check at the gate
(`claude_approved.refusal`: the approved list, the blocks, the contract yes, the USD caps).

THE STORE is one row per run in `review_shown_lists`: the document ids as a JSON list, so an empty list (a review that showed
nothing leaves) is different from no list. Ids only: never a file name or a title.

This module opens no socket and reads no document text.
"""

from __future__ import annotations

import json
import sqlite3

from .db import connect

TABLE = "review_shown_lists"
SPECIFICATION_ROLE = "SPECIFICATION"
NOT_SHOWN_WORDS = "not sent: this review cites a specification that was not on the list shown before the start"


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            run_id         TEXT PRIMARY KEY,
            documents_json TEXT NOT NULL,
            shown_at       TEXT NOT NULL
        )"""
    )


def record_in(conn, run_id: str, document_ids, now: str) -> None:
    """Store the list shown for this run WITHOUT committing, for the transaction that makes the run and its engine choice."""
    ensure_schema(conn)
    ids = sorted({str(d) for d in document_ids if d})
    conn.execute(
        f"INSERT OR REPLACE INTO {TABLE} (run_id, documents_json, shown_at) VALUES (?,?,?)",
        (run_id, json.dumps(ids), now),
    )


def shown_ids(conn, run_id: str | None) -> frozenset[str] | None:
    """The ids the run was started with, or None when no list was stored for it (no table, no row). A damaged row reads as an
    EMPTY list (nothing is on it); a database error propagates, so no caller reads "could not look" as "nothing to hold"."""
    if not run_id:
        return None
    has = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).fetchone()
    if has is None:
        return None
    row = conn.execute(
        f"SELECT documents_json FROM {TABLE} WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        got = json.loads(row["documents_json"])
    except ValueError:
        return frozenset()
    return frozenset(str(d) for d in got) if isinstance(got, list) else frozenset()


def unshown_specifications(conn, run_id: str, document_ids) -> frozenset[str]:
    """Of `document_ids`, the specifications that are not the paper under review `run_id` and are not on its stored list.
    Raises `sqlite3.Error` when the library cannot be read: the caller fails closed."""
    ids = sorted({str(d) for d in document_ids if d})
    if not ids:
        return frozenset()
    marks = ",".join("?" for _ in ids)
    specs = {
        r["document_id"]
        for r in conn.execute(
            f"SELECT document_id FROM document_classification WHERE document_role = ? AND document_id IN ({marks})",
            [SPECIFICATION_ROLE, *ids],
        )
    }
    if not specs:
        return frozenset()
    paper = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    specs.discard(paper["submittal_document_id"] if paper else None)
    if not specs:
        return frozenset()
    return frozenset(specs - (shown_ids(conn, run_id) or frozenset()))


def _cited_ids(conn, run_id: str) -> set[str]:
    """Every document the run may carry beside its paper: the standards applied to it, the rules the AI reviewer asked (its plan
    items) and the project papers of a general review (requested and accepted). A source whose table does not exist adds none."""
    ids: set[str] = set()
    queries = (
        (
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND COALESCE(included, 1) = 1"
        ),
        (
            "SELECT standard_document_id FROM agent_review_rule"
            " WHERE run_id = ? AND asked = 1 AND standard_document_id IS NOT NULL"
        ),
    )
    for sql in queries:
        try:
            ids |= {str(r[0]) for r in conn.execute(sql, (run_id,)) if r[0]}
        except sqlite3.OperationalError:
            continue
    try:
        row = conn.execute(
            "SELECT requested_json, project_json FROM agent_review_general WHERE run_id = ?", (run_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    for raw in (row or ()):
        try:
            got = json.loads(raw or "[]")
        except ValueError:
            continue
        ids |= {str(d) for d in got if isinstance(d, str) and d} if isinstance(got, list) else set()
    return ids


def cited_unshown(conn, run_id: str) -> int:
    """How many specifications this run carries beside its paper (see `_cited_ids`) that were not on its shown list. For the
    run's note."""
    try:
        return len(unshown_specifications(conn, run_id, _cited_ids(conn, run_id)))
    except sqlite3.Error:
        return 0
