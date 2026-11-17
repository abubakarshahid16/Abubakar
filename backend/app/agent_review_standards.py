"""The held standards' text for the AI reviewer's items (moved out of agent_review_items): clause bodies, table captions and
placed clause headings read from the stored pages by the same reader `get_clause` uses. Read only; no model call."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from . import agent_review_pass_guards as pass_guards
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


log = logging.getLogger(__name__)


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


def read_book(conn: Any, doc: str) -> pass_guards.Book:
    """The stored pages of one book on the caller's own connection: `pages.text`, and for a page whose text is empty the recognised
    text of the same page (`page_ocr`, no error; those pages are marked as scanned)."""
    rows = {
        int(r[0]): r[1] or ""
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (doc,)
        )
    }
    scanned: set[int] = set()
    if not rows or any(not t.strip() for t in rows.values()):
        try:
            for n, t in conn.execute(
                "SELECT page_no, text FROM page_ocr WHERE document_id = ? AND error IS NULL",
                (doc,),
            ):
                if int(n) not in rows or not rows[int(n)].strip():
                    rows[int(n)] = t or ""
                    scanned.add(int(n))
        except (
            sqlite3.Error
        ):  # an old database without the table: the pages table stands alone
            log.debug(
                "agent review: no recognised text table for the rule book %s", doc
            )
    return pass_guards.Book(rows, scanned)


class BookPages:
    """The books of one run, each read ONCE on the calling thread's own connection (a sqlite connection does not cross threads).
    Kept for the life of the run, then dropped."""

    def __init__(self) -> None:
        self._books: dict[str, pass_guards.Book] = {}
        self._lock = threading.Lock()

    def book(self, doc: Any) -> pass_guards.Book:
        key = str(doc or "")
        with self._lock:
            got = self._books.get(key)
        if got is None:
            from .db import connect

            got = read_book(connect(), key) if key else pass_guards.Book({})
            with self._lock:
                got = self._books.setdefault(key, got)
        return got


def verify(
    book_id: Any, quote: Any, page_hint: Any = None, books: BookPages | None = None
) -> pass_guards.Located:
    """(book id, quote, page hint) -> found / true page / where, searching the book's stored pages, never the stored requirement row.
    The ONE function for this check (the calculator does not call it yet; the AI lines go through `pass_guards.judge`). Pass one `BookPages` when asking many quotes (each book is read once)."""
    return pass_guards.locate(quote, (books or BookPages()).book(book_id), page_hint)


# ------------------------------------------------------------------------------------------------ book words shown on a CRS (order 14, G1)

#: The visible mark between two pieces of a rule's stored words that stand apart in the book (completeness rule 3: never an unmarked cut).
CUT_MARK = " … "
#: At most this many pieces: a text that needs more is not shown as the book's words.
MOST_PIECES = 3


def _piece_end(book: pass_guards.Book, words: list[str], i: int, page: int, start: int) -> tuple[int, int]:
    """(j, at): the most words from `i` whose folded text stands on `page` at or after `start` (j == i: none), and where it starts."""
    plain = book.plain(page)
    lo, hi, best = i + 1, len(words), (i, -1)
    while lo <= hi:  # a prefix of a found text is found at the same place: the longest is found by halving
        mid = (lo + hi) // 2
        at = plain.find(pass_guards._fold(" ".join(words[i:mid])), start)
        if at >= 0:
            best, lo = (mid, at), mid + 1
        else:
            hi = mid - 1
    return best


def book_words(doc: Any, text: Any, page_hint: Any = None, books: BookPages | None = None) -> str | None:
    """The rule's stored words as a CRS may show them as the BOOK's words (honesty rule 4, gate G1): the text itself when code finds it
    in the book's stored pages (`verify`); the text in pieces joined by `CUT_MARK` when its words stand in the book in this order with
    other text of the book between them (a running header over a page break: each later piece on the same page after the one before,
    or on the next page), at most `MOST_PIECES`, every piece at least `pass_guards.OFF_PAGE_MIN` characters (a shorter one proves
    nothing off its own page); None when code cannot find it (words an AI step or a reading wrote that are not the book's): such words
    are never shown as the book's text. Pure on the book's stored pages."""
    shown = " ".join(str(text or "").split())
    if not shown or not doc:
        return None
    books = books or BookPages()
    try:
        if verify(doc, shown, page_hint, books).found:
            return shown
        book, words = books.book(doc), shown.split()
    except sqlite3.Error:  # a database without the pages table holds no book: nothing is found
        log.debug("agent review: no stored pages to search for the rule book %s", doc)
        return None
    hints = [p for p in pass_guards._hints(page_hint) if p in book.pages]
    order = hints + sorted(set(book.pages) - set(hints))
    best = max(((_piece_end(book, words, 0, p, 0), -k, p) for k, p in enumerate(order)), default=None)
    if best is None or best[0][0] == 0:
        return None
    (i, at), _rank, page = best
    pieces = [" ".join(words[:i])]
    end = at + len(pass_guards._fold(pieces[0]))
    while i < len(words) and len(pieces) < MOST_PIECES:
        same = _piece_end(book, words, i, page, end)
        nxt = _piece_end(book, words, i, page + 1, 0) if page + 1 in book.pages else (i, -1)
        (j, at), page = (same, page) if same[0] >= nxt[0] else (nxt, page + 1)
        if j == i:
            return None
        pieces.append(" ".join(words[i:j]))
        end, i = at + len(pass_guards._fold(pieces[-1])), j
    if i < len(words) or any(len(p) < pass_guards.OFF_PAGE_MIN for p in pieces):
        return None
    return CUT_MARK.join(pieces)


# ------------------------------------------------------------------------------------------------ a clause shown on a CRS (order 14, G4)


def clause_holds(doc: Any, clause: Any, words: Any, page: Any, texts: dict | None = None) -> bool | None:
    """Does the cited clause hold the rule's words in the book's own text (honesty rule 4: no claim without a resolving citation)?
    True: code places the words (`subject_scope.StandardText.place`, on their page) inside a run of the clause's heading, before any
    heading that may end it. False: code places them and finds the clause's heading, but the words stand outside every run of it or
    after a heading that may end it (a clause number carried over a later heading: "the last clause seen" is no citation). None: code
    cannot tell (the words not placed, no heading of the clause found, no clause). `texts`: each book's text read once per caller."""
    from .db import connect

    if not doc or not str(clause or "").strip() or not str(words or "").strip():
        return None
    texts = {} if texts is None else texts
    if doc not in texts:
        try:
            pages = _paper_pages(connect(), str(doc))
        except sqlite3.Error:  # a database without the pages table: code cannot tell
            pages = []
        texts[doc] = subject_scope.StandardText(pages)
    text = texts[doc]
    runs = [run for key in _clause_keys(str(clause)) for run in text.spans(key)]
    at = text.place({"source_text": str(words), "page": page if isinstance(page, int) and not isinstance(page, bool) else None})
    if not runs or at is None:
        return None
    return any(lo <= at < soft for lo, soft, _hi in runs)
