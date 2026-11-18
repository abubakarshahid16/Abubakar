"""The reason each rule book was chosen, as a viewer may see it (order 14, piece H; rule 5).

A book's `why` is the scope step's own words (a model's free text, <= 120 characters). It can name ANOTHER book: by its file name, its
identifier (the catalog's "API-520-I") or its catalog alias ("B03"). A viewer who may not read that book must never learn its name
from someone else's reason, so a reason that names a book the viewer may not open is not served: the fixed words WHY_HIDDEN stand in
its place (the line is not edited: a scrubbed half-sentence would mislead). A missing reason says WHY_NOT_RECORDED, the same words on
the page and in the Excel file. No model, no network, no write.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

WHY_NOT_RECORDED = "the reason was not recorded for this review"
WHY_HIDDEN = "not shown: it names a book you may not read"

#: A squashed name shorter than this is never matched as text (too many false hits); an alias is matched as a whole word instead.
_MIN_NAME = 4
_ALIAS = re.compile(r"^[A-Za-z]\d{1,3}$")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _catalog_entries(conn, run: dict) -> list[dict]:
    """The saved checklist's book entries (alias, identifier, book id), or []: the catalog names the model saw."""
    from . import aim_review_store

    key, sha = run.get("checklist_key"), run.get("checklist_sha256")
    if not key or not sha:
        return []
    try:
        row = conn.execute(
            f"SELECT body_json FROM {aim_review_store.CHECKLISTS} WHERE key = ? AND sha256 = ?",
            (key, sha),
        ).fetchone()
        body = json.loads(row["body_json"]) if row and row["body_json"] else {}
    except (ValueError, TypeError, KeyError, sqlite3.Error):
        return []
    books = body.get("books") if isinstance(body, dict) else None
    return [b for b in books or [] if isinstance(b, dict)]


def _known_ids(conn, run: dict, ids: list[str], entries: list[dict]) -> set[str]:
    """Every document the model could have named: the run's books, the list shown before the start, the saved catalog's books."""
    from . import review_shown

    known = set(ids) | {str(b.get("book") or "") for b in entries}
    try:
        shown = review_shown.shown_ids(conn, run.get("run_id"))
    except sqlite3.Error:
        shown = None
    known |= set(shown or ())
    known.discard("")
    return known


def _hidden_names(
    conn, run: dict, scope, ids: list[str]
) -> tuple[list[str], list[str]]:
    """(squashed names, aliases) of every book the viewer may not read: its file name, its catalog identifier and alias (a chosen
    book's, from the saved checklist) and its library identifier (`library.identifier_of`: the document number or the identifier its
    file name holds), so a book that was listed but never chosen is caught by its identifier too."""
    from .aim_review import library

    entries = _catalog_entries(conn, run)
    hidden: list[str] = []
    files: dict[str, str] = {}
    for doc_id in sorted(_known_ids(conn, run, ids, entries)):
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is not None and scope.may_read(doc_id):
            continue
        hidden.append(doc_id)
        if row is not None:
            files[doc_id] = str(row["filename"] or "")
    by_id = {e["id"]: e for e in library.library(conn, within=frozenset(hidden))}
    names: list[str] = []
    aliases: list[str] = []
    for doc_id in hidden:
        raw = [files.get(doc_id, "")]
        raw += [Path(raw[0]).stem] if raw[0] else []
        if doc_id in by_id:
            raw += [
                library.identifier_of(by_id[doc_id]),
                str(by_id[doc_id].get("document_number") or ""),
            ]
        for e in entries:
            if str(e.get("book") or "") == doc_id:
                raw.append(str(e.get("identifier") or ""))
                alias = str(e.get("alias") or "")
                if _ALIAS.match(alias):
                    aliases.append(alias)
        names += [s for s in (_squash(r) for r in raw) if len(s) >= _MIN_NAME]
    return names, aliases


def served(
    conn, run: dict, scope, ids: list[str], why: dict[str, str]
) -> dict[str, str]:
    """{book id: the reason to show this viewer} for each id in `why`: the stored words; WHY_NOT_RECORDED when there are none;
    WHY_HIDDEN when they name a book this viewer may not read. `scope` None (the app's own counting): nothing is hidden."""
    names, aliases = (
        _hidden_names(conn, run, scope, ids) if scope is not None else ([], [])
    )
    out: dict[str, str] = {}
    for doc_id, text in why.items():
        text = str(text or "").strip()
        if not text:
            out[doc_id] = WHY_NOT_RECORDED
            continue
        squashed = _squash(text)
        hit = any(n in squashed for n in names) or any(
            re.search(rf"\b{re.escape(a)}\b", text, re.IGNORECASE) for a in aliases
        )
        out[doc_id] = WHY_HIDDEN if hit else text
    return out


def listed_and_used(conn, run: dict, ids: list[str]) -> dict | None:
    """{"listed": M, "used": N}: the documents listed before the start (besides the paper) and how many of them the run carried.
    Hidden books count in both, never named. None when no list was stored for the run (an older run): nothing is said."""
    from . import review_shown

    try:
        shown = review_shown.shown_ids(conn, run.get("run_id"))
    except sqlite3.Error:
        return None
    if shown is None:
        return None
    paper = str(run.get("paper_document_id") or "")
    listed = {d for d in shown if d != paper}
    n, m = len({i for i in ids if i in listed}), len(listed)
    return {
        "listed": m,
        "used": n,
        "sentence": f"Of the {m} other document{'' if m == 1 else 's'} listed before the start, {n} {'was' if n == 1 else 'were'} used.",
    }
