"""The book behind a checklist line of the calculator (order 14, lane A).

A checklist entry is written in our own words and names a book and a clause. Its line in the AI review must never print those
words as the book's (gate G1), and must never show a clause or a verdict of a book the library does not hold (gate G7). For each
(book, clause) this answers ONE of:

  * {"book_id", "quote", "page"}: the book is held, and a stored requirement text of that clause was FOUND by code in the book's
    own stored pages (`pass_guards.locate`, the review's one matcher): that text is the line's quote;
  * {"book_id"}: the book is held, but no text of that clause was found in its pages: the line shows no quote;
  * {"missing": name}: the library holds no document for the book (`applicability.find_standard`, the one lookup).

Reads the caller's database connection only: no model, no network, no write. Each answer and each book is read once.
"""

from __future__ import annotations

import sqlite3
from typing import Any


class ChecklistBooks:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._library: list[dict] | None = None
        self._books: dict[str, Any] = {}
        self._answers: dict[tuple[str, str], dict] = {}

    def _held(self, name: str) -> dict | None:
        from . import agent_review_rules, applicability

        if self._library is None:
            self._library = agent_review_rules.library_of(self._conn)
        return applicability.find_standard(self._library, name)

    def _book(self, doc: str):
        from .agent_review_standards import read_book

        if doc not in self._books:
            self._books[doc] = read_book(self._conn, doc)
        return self._books[doc]

    def _clause_texts(self, doc: str, clause: str) -> list[tuple[str, Any]]:
        try:
            return self._conn.execute(
                "SELECT source_text, page FROM standard_requirements WHERE standard_document_id = ? AND clause = ?"
                " AND superseded_at IS NULL AND COALESCE(source_text, '') <> '' ORDER BY page, id",
                (doc, clause),
            ).fetchall()
        except sqlite3.Error:
            return []

    def cite(self, standard: Any, clause: Any) -> dict:
        """The answer for one (book, clause); {} when the line names no book."""
        name, number = str(standard or "").strip(), str(clause or "").strip()
        if not name:
            return {}
        key = (name, number)
        if key not in self._answers:
            self._answers[key] = self._answer(name, number)
        return self._answers[key]

    def _answer(self, name: str, number: str) -> dict:
        from .agent_review_pass_guards import locate

        entry = self._held(name)
        if entry is None:
            return {"missing": name}
        doc = str(entry["id"])
        for text, page in self._clause_texts(doc, number) if number else []:
            found = locate(text, self._book(doc), page)
            if found.found:
                return {
                    "book_id": doc,
                    "quote": " ".join(text.split()),
                    "page": found.page,
                }
        return {"book_id": doc}
