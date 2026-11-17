"""The held standards' text for the AI reviewer's items (moved out of agent_review_items): clause bodies, table captions and
placed clause headings read from the stored pages by the same reader `get_clause` uses. Read only; no model call."""

from __future__ import annotations

import bisect
import itertools
import logging
import re
import sqlite3
import threading
import weakref
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
#: At most this many pieces (so at most two page breaks): a text that needs more is not shown as the book's words.
MOST_PIECES = 3
#: A running header or footer line: the same line (digits aside) on at least this share of the book's pages, and on 3 pages or more,
#: with at least this many letters (a book code such as "AB-CD-1" has 4; a bare number or clause id has none and is never one).
_RUNNING_SHARE, _RUNNING_LETTERS = 0.25, 3


def _digits_out(line: str) -> str:
    return re.sub(r"\d+", "#", line)


class _Body:
    """A book's stored text with its running header and footer lines and its page-number lines taken out (`_gap_line`): the folded
    lines (`pass_guards._fold`) joined by one space, each line's start, page, and whether such lines were taken out just before it."""

    def __init__(self, book: pass_guards.Book) -> None:
        numbers = sorted(book.pages)
        split = {n: [" ".join(r.split()) for r in book.pages[n].splitlines() if r.strip()] for n in numbers}
        seen: dict[str, set[int]] = {}
        for n in numbers:
            for line in split[n]:
                if len(re.findall(r"[A-Za-z]", line)) >= _RUNNING_LETTERS:
                    seen.setdefault(_digits_out(line), set()).add(n)
        least = max(3, _RUNNING_SHARE * len(numbers))
        running = {form for form, where in seen.items() if len(where) >= least}
        parts: list[str] = []
        self.starts: list[int] = []
        self.pages: list[int] = []
        self.gap_before: list[bool] = []
        at, dropped = 0, False
        for n in numbers:
            for line in split[n]:
                folded = pass_guards._fold(line)
                if _digits_out(line) in running or re.fullmatch(rf"[^0-9A-Za-z]*0*{n}[^0-9A-Za-z]*", line) or not folded:
                    dropped = True
                    continue
                at += 1 if parts else 0  # the joining space
                self.starts.append(at)
                self.pages.append(n)
                self.gap_before.append(dropped and bool(parts))
                parts.append(folded)
                at, dropped = at + len(folded), False
        self.text = " ".join(parts)


_BODIES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _body(book: pass_guards.Book) -> _Body:
    got = _BODIES.get(book)
    if got is None:
        got = _BODIES[book] = _Body(book)
    return got


def _word_hits(text: str, q: str):
    """Every start of `q` in `text` on whole words: a match that begins or ends inside a word of the book ("5" in "50") is none."""
    start = 0
    while (at := text.find(q, start)) >= 0:
        end, start = at + len(q), at + 1
        if (at == 0 or not (text[at - 1].isalnum() and q[0].isalnum())) and (
            end == len(text) or not (text[end].isalnum() and q[-1].isalnum())
        ):
            yield at


def _pieces(body: _Body, words: list[str], q: str, at: int) -> list[str] | None:
    """The stored words in pieces at the page breaks where the match at `at` skips the book's running lines; None when it skips them
    anywhere else, needs more than `MOST_PIECES` pieces, skips nothing, or a piece is shorter than `pass_guards.OFF_PAGE_MIN`."""
    first, last = bisect.bisect_right(body.starts, at) - 1, bisect.bisect_right(body.starts, at + len(q) - 1) - 1
    cuts = [k for k in range(first + 1, last + 1) if body.gap_before[k]]
    if not cuts or len(cuts) >= MOST_PIECES or any(body.pages[k] != body.pages[k - 1] + 1 for k in cuts):
        return None
    marks = [0] + [q[: body.starts[k] - at].count(" ") for k in cuts] + [len(words)]
    pieces = [" ".join(words[a:b]) for a, b in itertools.pairwise(marks)]
    return pieces if all(len(p) >= pass_guards.OFF_PAGE_MIN for p in pieces) else None


def book_words(doc: Any, text: Any, page_hint: Any = None, books: BookPages | None = None) -> str | None:
    """The rule's stored words as a CRS may show them as the BOOK's words (honesty rule 4, gate G1): the text itself when code finds it
    in the book's stored pages (`verify`); in pieces joined by `CUT_MARK` ONLY where the book's text between them is a page break and
    nothing but the book's running header and footer lines and the page's own number (`_Body`): whole words only, every word of the
    stored text kept in order, at most `MOST_PIECES` pieces on consecutive pages, every piece at least `pass_guards.OFF_PAGE_MIN`
    characters (a shorter piece is searched on its stated page only, so the gate could not find it on the next). Any other gap (a word
    of the book left out, such as a "not", text of the same page, a page further on) or a cut inside a word: None, and such words are
    never shown as the book's text. Pure on the book's stored pages."""
    shown = " ".join(str(text or "").split())
    if not shown or not doc:
        return None
    books = books or BookPages()
    try:
        if verify(doc, shown, page_hint, books).found:
            return shown
        book = books.book(doc)
    except sqlite3.Error:  # a database without the pages table holds no book: nothing is found
        log.debug("agent review: no stored pages to search for the rule book %s", doc)
        return None
    words = shown.split()
    q, body = " ".join(pass_guards._fold(w) for w in words), _body(book)
    hints = set(pass_guards._hints(page_hint))
    hits = sorted(_word_hits(body.text, q), key=lambda a: (body.pages[bisect.bisect_right(body.starts, a) - 1] not in hints, a))
    for at in hits:
        pieces = _pieces(body, words, q, at)
        if pieces:
            return CUT_MARK.join(pieces)
    return None


# ------------------------------------------------------------------------------------------------ a clause shown on a CRS (order 14, G4)

#: `clause_holds`: code cannot say the rule's words are in the clause, nor that they are outside it (a heading that MAY end it, a parent
#: heading, or a certain end on another page stands between): the clause is "not checked", never "the rule's words are not in it".
CLAUSE_UNSURE = "unsure"


def _id_line(lines: list[str], i: int, running: set[str]) -> tuple[str, str, bool] | None:
    """(kind, id, bare) when line `i` of a page reads as a clause heading: `subject_scope._heading` (a title on the line), or a numbered
    id alone on its line with a title word on the next line (bare; its number need not follow the last heading read, so a body heading
    after a contents page that was not recognised as one is still read). Never a running header or footer."""
    if _digits_out(lines[i]) in running:
        return None
    head = subject_scope._heading(lines[i])
    if head:
        return head[0], head[1], False
    bare = subject_scope._BARE_NUMBER.match(lines[i])
    if bare and i + 1 < len(lines) and re.match(subject_scope._TITLE_WORD, lines[i + 1]) and _digits_out(lines[i + 1]) not in running:
        return "number", bare.group("id"), True
    return None


class ClauseText:
    """A book's text for `clause_holds`: every stored line with its page, its start in the folded text (`subject_scope._key`, the same
    fold `subject_scope.StandardText` places sentences with) and its reading as a clause heading (`_id_line`; none on a contents page)."""

    def __init__(self, pages: list[tuple[int, str]]) -> None:
        split = [(n, [" ".join(r.split()) for r in (t or "").splitlines() if r.strip()]) for n, t in pages]
        running = subject_scope._running_lines([lines for _n, lines in split])
        self.page_of: list[int] = []
        self.offsets: list[int] = []
        self.ids: list[tuple[str, str, bool] | None] = []
        self.bounds: dict[int, tuple[int, int]] = {}
        parts, at = [], 0
        for n, lines in split:
            start, contents = at, subject_scope.contents_page(lines)
            for i, line in enumerate(lines):
                self.page_of.append(n)
                self.offsets.append(at)
                self.ids.append(None if contents else _id_line(lines, i, running))
                parts.append(subject_scope._key(line))
                at += len(parts[-1])
            self.bounds[n] = (start, at)
        self.folded = "".join(parts)

    def starts(self, words: Any, page: int) -> list[int]:
        """Every place the words start on `page`: the whole words first; when they are not whole on the page (they run over its end),
        every place their opening (`subject_scope._PLACE_CHARS`) starts on it. Never only the first hit: two rules may open alike."""
        key, bounds = subject_scope._key(words), self.bounds.get(page)
        if bounds is None or len(key) < subject_scope._PLACE_MIN:
            return []
        for probe in (key, key[: subject_scope._PLACE_CHARS]):
            hits, at = [], self.folded.find(probe, bounds[0])
            while 0 <= at < bounds[1]:
                hits.append(at)
                at = self.folded.find(probe, at + 1)
            if hits:
                return hits
        return []

    def where(self, key: tuple[str, str], at: int) -> bool | str | None:
        """Is the text starting at `at` in clause `key`? Read back from it, over its own page and the page before, to the nearest heading
        that decides: the clause itself or a part of it True; another clause of its own family (`subject_scope._ends_for_certain`: "4.2"
        or "4.0" for "4.1"), titled on its line and on the SAME page, False (certain); any other heading that may end it, a bare one, a
        certain end on the page before, or a parent ("4" for "4.1": the words come before the clause's own heading) `CLAUSE_UNSURE`.
        No deciding heading on the two pages: None (cannot tell)."""
        i = bisect.bisect_right(self.offsets, at) - 1
        page = self.page_of[i] if i >= 0 else None
        while i >= 0 and self.page_of[i] >= page - 1:
            got = self.ids[i]
            if got:
                kind, ident, bare = got
                if kind == key[0] and subject_scope._stored_clause_in(ident, key):
                    return True
                if subject_scope._ends_for_certain(key, (kind, ident)):
                    return False if not bare and self.page_of[i] == page else CLAUSE_UNSURE
                if subject_scope._ends(key, (kind, ident)) or (kind == key[0] == "number" and key[1].startswith(ident + ".")):
                    return CLAUSE_UNSURE
            i -= 1
        return None


def _together(found: list) -> bool | str | None:
    """One answer from several: True if any is True; False only if every one is False; else `CLAUSE_UNSURE` if any is; else None."""
    if True in found:
        return True
    if found and all(f is False for f in found):
        return False
    return CLAUSE_UNSURE if CLAUSE_UNSURE in found else None


def clause_holds(doc: Any, clause: Any, words: Any, page: Any, texts: dict | None = None) -> bool | str | None:
    """Does the cited clause hold the rule's words in the book's own text (honesty rule 4: no claim without a resolving citation)?
    Judged at EVERY place the words start on their verified page (`ClauseText.starts`) by the nearest deciding heading before them
    (`ClauseText.where`), only on body pages (a contents page has no headings). True: in the clause (any place). False, ONLY when code
    is certain at every place: a certain end of the clause titled on the words' own page stands between. `CLAUSE_UNSURE`: a heading
    that may end it stands between (the clause is not checked, never called wrong). None: code cannot tell (no heading of the clause
    in the book, the words not on the page, no deciding heading near them). `texts`: each book's `ClauseText` read once per caller."""
    from .db import connect

    if not doc or not str(clause or "").strip() or not str(words or "").strip():
        return None
    if not isinstance(page, int) or isinstance(page, bool):
        return None
    texts = {} if texts is None else texts
    if doc not in texts:
        try:
            pages = _paper_pages(connect(), str(doc))
        except sqlite3.Error:  # a database without the pages table: code cannot tell
            pages = []
        texts[doc] = ClauseText(pages)
    text = texts[doc]
    keys = [k for k in _clause_keys(str(clause)) if any(g and (g[0], g[1]) == k for g in text.ids)]
    hits = text.starts(words, page)
    if not keys or not hits:
        return None
    return _together([_together([text.where(k, at) for k in keys]) for at in hits])
