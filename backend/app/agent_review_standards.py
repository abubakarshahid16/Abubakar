"""The held standards' text for the AI reviewer's items (moved out of agent_review_items): clause bodies, table captions and
placed clause headings read from the stored pages by the same reader `get_clause` uses. Read only; no model call."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import standard_ids, subject_scope


def _label(filename: str | None) -> str | None:
    """A standard's name from its file name: the stem (no extension)."""
    if not filename:
        return None
    return Path(filename).stem.strip() or None


#: A table caption line: "Table <id>" (letters, digits, dashes, dots) at the start of a line.
_TABLE_CAPTION = re.compile(
    r"^(?P<cap>Table\s+[A-Z0-9][A-Z0-9.\-]*[A-Z0-9])\b", re.IGNORECASE
)


def _fold_words(text: object) -> str:
    return re.sub(r"[^0-9a-z]", "", str(text or "").lower())


def _norm_clause(clause: object) -> str:
    return re.sub(r"\s+", "", str(clause or "")).upper().rstrip(".")


def _clause_keys(clause: str) -> list[tuple[str, str]]:
    ident = _norm_clause(clause)
    return [(k, ident) for k in ("number", "lettered", "appendix")] if ident else []


def _paper_pages(conn: sqlite3.Connection, doc: str) -> list[tuple[int, str]]:
    return [
        (r["page_no"], r["text"] or "")
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (doc,),
        )
    ]


class _Standards:
    """Held standards' text, read once per document (StandardText: the same reader get_clause uses)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._text: dict[str, subject_scope.StandardText] = {}
        self._held: list[tuple[str, str]] | None = None

    def text(self, doc: str) -> subject_scope.StandardText:
        if doc not in self._text:
            self._text[doc] = subject_scope.StandardText(_paper_pages(self.conn, doc))
        return self._text[doc]

    def held(self) -> list[tuple[str, str]]:
        """(document id, name) of every document that holds standard rules."""
        if self._held is None:
            self._held = [
                (r["id"], _label(r["filename"]) or r["id"])
                for r in self.conn.execute(
                    "SELECT d.id, d.filename FROM documents d WHERE d.id IN"
                    " (SELECT DISTINCT standard_document_id FROM standard_requirements)"
                    " ORDER BY d.filename"
                )
            ]
        return self._held

    def resolve(self, name: str, prefer: set[str]) -> str | None:
        """The held document for a standard name; one the paper's rules already use wins."""
        hits = [
            d for d, label in self.held() if standard_ids.same_standard(name, label)
        ]
        for d in hits:
            if d in prefer:
                return d
        return hits[0] if hits else None

    def _page_at(self, text: subject_scope.StandardText, offset: int) -> int | None:
        for page, (start, end) in text.page_bounds.items():
            if start <= offset < end or (start == end == offset):
                return page
        return None

    def clause(self, doc: str, clause: str) -> tuple[str | None, int | None]:
        """(clause body, page where it starts), as get_clause reads it; (None, None) when not found."""
        text = self.text(doc)
        for key in _clause_keys(clause):
            spans = text.spans(key)
            if spans:
                start, _soft, end = spans[0]
                lines = [
                    ln
                    for ln, off in zip(text.lines, text.offsets, strict=False)
                    if start <= off < end
                ]
                body = "\n".join(lines).strip()
                if body:
                    return body, self._page_at(text, start)
        return None, None

    def page_lines(self, doc: str, page: int | None) -> list[str]:
        if page is None:
            return []
        row = self.conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?", (doc, page)
        ).fetchone()
        return (
            [" ".join(x.split()) for x in (row["text"] or "").splitlines() if x.strip()]
            if row
            else []
        )

    def table_clause(
        self, doc: str, requirement: dict
    ) -> tuple[str | None, str | None, int | None]:
        """For a rule read from a table row: (table caption, caption-to-page-end text, page).
        The caption is the last "Table <id>" line before the row on its page, else the first one on
        the page, else the last one on the page before (a table carried over). (None,)*3 if none."""
        page = requirement.get("page")
        lines = self.page_lines(doc, page)
        caps = [i for i, ln in enumerate(lines) if _TABLE_CAPTION.match(ln)]
        row_key = _fold_words(requirement.get("source_text"))[:40]
        at = None
        if row_key:
            for i, ln in enumerate(lines):
                if row_key[:20] and row_key[:20] in _fold_words(ln):
                    at = i
                    break
        pick = None
        if caps:
            before = [i for i in caps if at is not None and i <= at]
            pick = before[-1] if before else caps[0]
            body = lines[pick:]
        else:
            prev = self.page_lines(doc, (page or 0) - 1)
            pcaps = [i for i, ln in enumerate(prev) if _TABLE_CAPTION.match(ln)]
            if not pcaps:
                return None, None, None
            pick, page = pcaps[-1], page - 1
            body = prev[pick:] + lines
            lines = prev
        caption = _TABLE_CAPTION.match(lines[pick]).group("cap")
        return caption, "\n".join(body).strip() or None, page

    def page_clause(self, doc: str, page: int | None) -> str | None:
        """The clause in force at the top of `page`: the last heading opened before the page starts,
        else the first heading on the page. A weaker link than a stored or placed clause."""
        text = self.text(doc)
        bounds = text.page_bounds.get(page)
        if bounds is None:
            return None
        before = on_page = None
        for index, head in enumerate(text.heads):
            if head is None or index in text.bare:
                continue
            off = text.offsets[index]
            if off < bounds[0]:
                before = head
            elif off < bounds[1] and on_page is None:
                on_page = head
        found = before or on_page
        return found[1] if found else None

    def before_first_heading(self, doc: str, page: int | None) -> bool:
        """Does `page` end before the standard's first heading (a cover, foreword or contents page)?"""
        text = self.text(doc)
        bounds = text.page_bounds.get(page)
        if bounds is None:
            return False
        first = next(
            (
                text.offsets[i]
                for i, h in enumerate(text.heads)
                if h is not None and i not in text.bare
            ),
            None,
        )
        return first is None or bounds[1] <= first

    def placed_clause(self, doc: str, requirement: dict) -> str | None:
        """The numbered/lettered heading above where the rule's sentence sits, or None."""
        text = self.text(doc)
        at = text.place(requirement)
        if at is None:
            return None
        found = None
        for index, head in enumerate(text.heads):
            if text.offsets[index] > at:
                break
            if head is not None and index not in text.bare:
                found = head
        return found[1] if found else None
