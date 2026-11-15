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


def held_documents(conn, run_id: str, document_ids) -> frozenset[str]:
    """Of `document_ids`, the ones the gate holds for review run `run_id`. A run WITH a stored list sends only what it names: any
    other document, of any kind, is held. A run without one holds the specifications that are not the paper under review (the
    older routes show no list). Raises `sqlite3.Error` when the library cannot be read: the caller fails closed."""
    ids = sorted({str(d) for d in document_ids if d})
    if not ids:
        return frozenset()
    stored = shown_ids(conn, run_id)
    if stored is not None:
        return frozenset(ids) - stored
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
    return frozenset(specs)


def unshown_specifications(conn, run_id: str, document_ids) -> frozenset[str]:
    """The name the gate and the integrator's tests use: what `held_documents` says (a run with a stored list holds every document
    it does not name; a run without one holds the specifications that are not its paper)."""
    return held_documents(conn, run_id, document_ids)


def drop_unlisted(conn, run_id: str, doc: dict) -> list[str]:
    """THE UPSTREAM DROP of the AI reviewer: with a stored list, the items of any rule book the list does not name are removed from
    the plan BEFORE a request is built, so their rules are not asked and none of their text is sent, and the run goes on with
    everything that is listed. Returns the dropped books' ids (the run counts them). Items with no rule book (checklists) stay.
    The send-time check in `claude_approved.refusal` remains the last line of defence. No list stored: nothing dropped."""
    shown = shown_ids(conn, run_id)
    if shown is None:
        return []
    from .agent_review_rules import NOT_ON_LIST

    items = doc.get("items") or []
    ids = {
        str(i["standard_document_id"]) for i in items if i.get("standard_document_id")
    }
    dropped = ids - shown
    if dropped:
        doc["items"] = [
            i for i in items if str(i.get("standard_document_id") or "") not in dropped
        ]
    # the rules `build_items_for_run` already left out of the plan (reason NOT_ON_LIST) belong to books dropped the same way
    left = (doc.get("rule_labels") or {}).get("left_out") or []
    dropped |= {
        str(r["standard_document_id"])
        for r in left
        if r.get("reason") == NOT_ON_LIST and r.get("standard_document_id")
    }
    return sorted(dropped)


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
            "SELECT requested_json, project_json FROM agent_review_general WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    for raw in row or ():
        try:
            got = json.loads(raw or "[]")
        except ValueError:
            continue
        ids |= (
            {str(d) for d in got if isinstance(d, str) and d}
            if isinstance(got, list)
            else set()
        )
    return ids


def held_applied(
    conn, run_id: str, applied_run: str | None = None, extra=()
) -> list[str]:
    """The documents this run carries beside its paper (`_cited_ids`: the applied standards, the rules the AI reviewer asked, the
    project papers of a general review; also those of `applied_run`, the run the AI reviewer's standards were chosen on, and
    `extra`) that the list shown before the start left out: what the gate holds. Empty on a database error."""
    try:
        ids = _cited_ids(conn, run_id)
        if applied_run:
            ids |= _cited_ids(conn, applied_run)
        ids |= {str(e) for e in extra}
        return sorted(held_documents(conn, run_id, ids))
    except sqlite3.Error:
        return []


def cited_unshown(conn, run_id: str, applied_run: str | None = None, extra=()) -> int:
    """How many documents applied to this run were held because no list shown before the start names them. For the run's note."""
    return len(held_applied(conn, run_id, applied_run, extra))


def found_during_review(
    conn, run_id: str, applied_run: str | None = None, extra=()
) -> int:
    """Of those, the rule books (not specifications): the ones the review found only while it ran, the screen's "N more rule books
    apply to this paper"."""
    held = held_applied(conn, run_id, applied_run, extra)
    if not held:
        return 0
    marks = ",".join("?" for _ in held)
    specs = conn.execute(
        f"SELECT COUNT(*) FROM document_classification WHERE document_role = ? AND document_id IN ({marks})",
        [SPECIFICATION_ROLE, *held],
    ).fetchone()[0]
    return len(held) - specs


def cap(plan: dict, shown_document_ids) -> list[str]:
    """The list a start stores: what the screen showed, narrowed to what the plan lists NOW. A document the screen did not show is
    never added; one the plan no longer lists is dropped. Only NARROWS."""
    now = {d["id"] for d in (plan.get("documents") or {}).get("leaving") or []}
    return sorted({str(d) for d in shown_document_ids} & now)


def without_titles(plan: dict) -> dict:
    """The plan as it is stored with the run: the leaving list by id, kind and reason only (the stored choice holds words and ids,
    never a file name)."""
    docs = dict(plan.get("documents") or {})
    # ids and counts only: not the file names of the paper's earlier rule books either
    docs["rule_books_count"] = len(docs.pop("rule_books", None) or [])
    docs.pop("rule_books_note", None)
    if "leaving" in docs:
        docs["leaving"] = [
            {k: d.get(k) for k in ("id", "kind", "why")} for d in docs["leaving"]
        ]
        docs["not_sent"] = [
            {k: d.get(k) for k in ("kind", "why", "reason")}
            for d in docs.get("not_sent") or []
        ]
    return {**plan, "documents": docs}


# ---- the consent of an explicit choice of Claude (owner, 12 Nov 2026, #1584: "button is enough") -------------------------------

CONSENT_TABLE = "review_claude_consent"


def ensure_consent_schema(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {CONSENT_TABLE} (
            run_id         TEXT PRIMARY KEY,
            user_id        TEXT,
            engine         TEXT NOT NULL,
            documents_json TEXT NOT NULL,
            consented_at   TEXT NOT NULL
        )"""
    )


def record_consent_in(
    conn, run_id: str, user_id: str | None, documents: list[dict], now: str
) -> None:
    """Write, WITHOUT committing (the start's own transaction), that this user started this run with the explicit choice of Claude
    and which documents the screen listed: each one's id, kind, role and file hash. Ids, kinds, roles and hashes only: never a
    title and never any text."""
    ensure_consent_schema(conn)
    rows = [{k: d.get(k) for k in ("id", "kind", "role", "sha256")} for d in documents]
    conn.execute(
        f"INSERT OR REPLACE INTO {CONSENT_TABLE} (run_id, user_id, engine, documents_json, consented_at) VALUES (?,?,?,?,?)",
        (run_id, user_id, "claude", json.dumps(rows, sort_keys=True), now),
    )


def consent_of(conn, run_id: str | None) -> dict | None:
    """The consent record of a run, or None when the run was not started with the explicit choice of Claude (no table, no row).
    A damaged row reads as no consent."""
    if not run_id:
        return None
    has = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (CONSENT_TABLE,),
    ).fetchone()
    if has is None:
        return None
    row = conn.execute(
        f"SELECT * FROM {CONSENT_TABLE} WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        docs = json.loads(row["documents_json"])
    except ValueError:
        return None
    if not isinstance(docs, list):
        return None
    return {
        "user_id": row["user_id"],
        "at": row["consented_at"],
        "documents": {str(d.get("id")): d for d in docs if isinstance(d, dict)},
    }


_ANY_CALLER = object()


def consented_ids(conn, run_id: str | None, ids, caller=_ANY_CALLER) -> frozenset[str]:
    """Of `ids`, the documents the run's consent record covers AND whose file is still the one that was listed (a replaced
    revision is not covered) AND that the run's stored list still names. Raises `sqlite3.Error`: the caller fails closed."""
    got = consent_of(conn, run_id)
    if got is None:
        return frozenset()
    if caller is not _ANY_CALLER and caller != got["user_id"]:
        return frozenset()  # per run AND per user: another person calling a Claude route on this run gets no consent from it
    listed = shown_ids(conn, run_id) or frozenset()
    wanted = sorted({str(i) for i in ids if i} & set(got["documents"]) & listed)
    if not wanted:
        return frozenset()
    marks = ",".join("?" for _ in wanted)
    now = {
        r["id"]: (r["sha256"] or "").strip().lower()
        for r in conn.execute(
            f"SELECT id, sha256 FROM documents WHERE id IN ({marks})", wanted
        )
    }
    return frozenset(
        d
        for d in wanted
        if now.get(d)
        and now[d] == str(got["documents"][d].get("sha256") or "").strip().lower()
    )


def consent_documents(conn, plan: dict, shown_ids_list) -> list[dict]:
    """The documents a start's consent record names: the list stored with the run (`cap`), each with its kind from the plan and
    its role and file hash from the library. Ids, kinds, roles and hashes only."""
    stored = cap(plan, shown_ids_list)
    kinds = {
        d["id"]: d.get("kind")
        for d in (plan.get("documents") or {}).get("leaving") or []
    }
    if not stored:
        return []
    marks = ",".join("?" for _ in stored)
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT d.id AS id, d.sha256 AS sha256, c.document_role AS role FROM documents d"
            f" LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id IN ({marks})",
            stored,
        )
    }
    return [
        {
            "id": i,
            "kind": kinds.get(i),
            "role": rows[i]["role"],
            "sha256": (rows[i]["sha256"] or "").strip().lower(),
        }
        for i in stored
        if i in rows
    ]
