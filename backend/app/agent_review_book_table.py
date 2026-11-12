"""The book-by-book table of the Rules used page: which held rule books were candidates for a review and which were not.

Read only, from tables the run already wrote: `review_applicable_standards` (the book selection: included or only
considered, and the METHOD that decided), `agent_review_rule` (per rule: asked, or left out with one reason, and its book)
and `standard_requirements` (how many rules a book stores). The selection's own free-text reason is NEVER shown (it can
quote the paper); only the fixed words below. Rule 5: a book the viewer may not read is counted, never named; the table
only narrows. Rule 4: every count states its boundary. No model, no network, nothing written.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

BOUNDARY = (
    "rule books in the library the person viewing this may read; rules counted are the rules stored for each book, "
    "asked and left out are this review's own"
)
#: the fixed words per selection method (applicability.METHOD_*); a method not listed reads "method not recorded".
METHOD_WORDS = {
    "referenced": "named in the paper",
    "governing_standard": "governs this equipment type (the project's governing-standards table)",
    "equipment_type": "mapped to this equipment type",
    "scope": "its own scope clause names this equipment",
    "service": "matches the paper's service",
    "project": "named by the project",
    "manual": "chosen by a person",
    "possible_citation": "its number looks like one the paper names; not confirmed",
    "semantic": "similar text only: a reason to look, not evidence that it governs",
    "discipline": "same discipline only: a reason to look, not evidence that it governs",
}
NOT_RECORDED = "method not recorded"
PER_RULE = "taken from a stored per-rule scope decision"
NO_SELECTION_NOTE = (
    "No book selection was stored for this review: its rules came from stored per-rule scope decisions, so only the "
    "books of those rules are listed."
)


def _name(filename: str | None, doc_id: str) -> str:
    stem = Path(filename).stem.strip() if filename else ""
    return stem or doc_id


def build(
    conn: sqlite3.Connection,
    run_id: str,
    may_read: Callable[[str], bool],
) -> dict:
    """{'books': [row dicts], 'hidden_books': int, 'note': str | None}, books the viewer may read only."""
    try:
        sel = conn.execute(
            "SELECT standard_document_id, included, selection_method FROM review_applicable_standards"
            " WHERE review_run_id = ?",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        sel = []
    rules = conn.execute(
        "SELECT standard_document_id, asked, left_out_reason FROM agent_review_rule WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    asked: dict[str, int] = {}
    left: dict[str, dict[str, int]] = {}
    for r in rules:
        doc = r["standard_document_id"]
        if not doc:
            continue
        if r["asked"]:
            asked[doc] = asked.get(doc, 0) + 1
        else:
            reasons = left.setdefault(doc, {})
            reasons[r["left_out_reason"]] = reasons.get(r["left_out_reason"], 0) + 1
    method: dict[str, tuple[bool, str]] = {}
    for r in sel:
        # the method is stored per row; a book with several rows keeps the including one
        inc = bool(r["included"])
        old = method.get(r["standard_document_id"])
        if old is None or (inc and not old[0]):
            method[r["standard_document_id"]] = (
                inc,
                METHOD_WORDS.get(str(r["selection_method"] or ""), NOT_RECORDED),
            )
    for doc in set(asked) | set(left):
        method.setdefault(doc, (True, PER_RULE))
    docs = sorted(method)
    readable = [d for d in docs if may_read(d)]
    hidden = len(docs) - len(readable)
    names: dict[str, str] = {}
    stored: dict[str, int] = {}
    for i in range(0, len(readable), 400):
        chunk = readable[i : i + 400]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", chunk
        ):
            names[r["id"]] = _name(r["filename"], r["id"])
        for r in conn.execute(
            f"SELECT standard_document_id, COUNT(*) AS n FROM standard_requirements"
            f" WHERE standard_document_id IN ({marks}) GROUP BY standard_document_id",
            chunk,
        ):
            stored[r["standard_document_id"]] = int(r["n"])
    rows = [
        {
            "rule_book": names.get(d, d),
            "in_review": method[d][0],
            "method": method[d][1],
            "stored_rules": stored.get(d, 0),
            "asked": asked.get(d, 0),
            "left_out": dict(sorted(left.get(d, {}).items())),
        }
        for d in readable
    ]
    rows.sort(key=lambda r: (not r["in_review"], -r["asked"], r["rule_book"]))
    return {
        "books": rows,
        "hidden_books": hidden,
        "note": None if sel else (NO_SELECTION_NOTE if rows else None),
    }
