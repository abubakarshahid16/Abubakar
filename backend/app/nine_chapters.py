"""Real chapters of a rule book for the nine-role reviewer (SPEC section C). Pure: stored page text in, chapters out. No model, no network,
no database; no book, layout or word list (rule 13).

A chapter is the span of a heading at the SHALLOWEST depth whose text fits the size limit: start at the top-level headings, replace a
chapter that is over the limit by its sub-headings, and so on down. A chapter over the limit with no sub-heading is split into parts on
page ends (then on line starts); each part repeats the last `OVERLAP_CHARS` of the one before. Text before the first heading is front
matter: never a chapter, never sent, counted. A book with no heading code can find is read in windows of `WINDOW_PAGES` pages with one
page repeated. The text of a part is EXACTLY the stored lines of that span (plus the repeated tail), nothing cleaned, so a quote is checked
against the same text it was read from. The headings are the app's own reader (`subject_scope.StandardText`: numbered, lettered,
appendix); the pages are the caller's (`agent_review_standards.read_book` gives a scanned book's recognised text the same way)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .nine_contract import Chapter, ChapterPart

#: Characters per token the spend estimator uses (`claude_spend`: characters / 3).
CHARS_PER_TOKEN = 3
#: Tokens of chapter text per model call (SPEC C): Claude 40,000; Local about 5,000.
CLAUDE_CALL_TOKENS = 40_000
LOCAL_CALL_TOKENS = 5_000
#: Tokens of chapter text per book and per review (SPEC C).
CLAUDE_BOOK_TOKENS, CLAUDE_REVIEW_TOKENS = 120_000, 200_000
LOCAL_REVIEW_TOKENS = 60_000
#: A part repeats the last characters of the one before it.
OVERLAP_CHARS = 1_500
#: A book with no heading is read in windows of this many pages with one page repeated.
WINDOW_PAGES = 12
WINDOW_REPEAT = 1
#: Consecutive chapters smaller than this are read as one unit (a book of many one-paragraph headings is not hundreds of units); never
#: over the call limit. The unit keeps every heading it holds in `covers`.
MIN_CHAPTER_CHARS = 1_500


@dataclass(frozen=True)
class CutBook:
    """The chapters of one book and what is needed to read their text again. `text(chapter_id, part_no)` is exactly what is sent."""

    book_id: str
    chapters: tuple[Chapter, ...]
    front_matter_chars: int
    front_matter_pages: tuple[int, ...]
    cut_by: str  # "heading" or "page window"
    note: str | None  # e.g. "no headings found: read by page windows"
    max_chars: int
    _lines: tuple[str, ...] = field(repr=False, default=())
    _line_page: tuple[int, ...] = field(repr=False, default=())
    _spans: Mapping[str, tuple[tuple[int, int, int], ...]] = field(repr=False, default_factory=dict)  # id -> ((line_from, line_to, tail_chars) per part)
    covers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # chapter id -> the heading ids it holds (itself, and the small ones joined to it)

    def text(self, chapter_id: str, part_no: int = 1) -> str:
        """The text of one part: the repeated tail of the part before it (parts 2 and up), then the stored lines."""
        spans = self._spans[chapter_id]
        line_from, line_to, tail = spans[part_no - 1]
        body = "\n".join(self._lines[line_from:line_to])
        if part_no > 1 and tail:
            prev_from, prev_to, _ = spans[part_no - 2]
            before = "\n".join(self._lines[prev_from:prev_to])
            body = before[-tail:] + "\n" + body
        return body

    def chapter(self, chapter_id: str) -> Chapter | None:
        return next((c for c in self.chapters if c.chapter_id == chapter_id), None)

    def locate(self, clause: str) -> str | None:
        """The id of the chapter that holds a clause number ("5.4.2.1" lies in chapter "5.4" or in a unit that covers "5.4.2"): the heading
        itself, else its longest parent on a dot boundary, else its family or appendix. None when no chapter holds it."""
        want = re.sub(r"\s+", "", str(clause or "")).upper()
        if not want:
            return None
        index = {h.upper().replace(" ", ""): cid for cid, hs in self.covers.items() for h in hs}
        while want:
            if want in index:
                return index[want]
            if "." in want:
                want = want.rsplit(".", 1)[0]
            elif "-" in want:
                want = want.split("-", 1)[0]
            else:
                return index.get("APPENDIX" + want)
        return None

    @property
    def total_chars(self) -> int:
        return sum(c.chars for c in self.chapters)


def tokens_of(chars: int) -> int:
    """The estimate every budget here uses: characters / `CHARS_PER_TOKEN`, rounded up."""
    return -(-int(chars) // CHARS_PER_TOKEN)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- headings -> a tree of spans


@dataclass
class _Node:
    key: str  # the chapter id
    depth: int
    line: int  # the heading's line index
    end: int = 0  # one past the last line (set when it closes)
    children: list[_Node] = field(default_factory=list)
    virtual: bool = False  # a family node made by code for lettered headings of one family ("UG-1", "UG-2" -> "UG")


def _depth_of(kind: str, ident: str) -> int:
    if kind == "number":
        return max(1, len(ident.split(".")))
    return 1  # appendix, article


def _label_of(kind: str, ident: str) -> str:
    return {"appendix": f"Appendix {ident}", "article": f"Article {ident}"}.get(kind, ident)


def _tree(heads: list[tuple[str, str] | None], n_lines: int) -> list[_Node]:
    """The headings in reading order as a forest. Lettered headings ("XX-12") hang under one virtual family node ("XX") so a book of
    hundreds of short paragraphs of a few families is not hundreds of top-level chapters."""
    roots: list[_Node] = []
    stack: list[_Node] = []

    def close(upto: int, at: int) -> None:
        while stack and stack[-1].depth >= upto:
            stack.pop().end = at

    for at, head in enumerate(heads):
        if head is None:
            continue
        kind, ident = head
        if kind == "lettered":
            family = re.match(r"[A-Z]+", ident).group(0) if re.match(r"[A-Z]+", ident) else ident
            top = stack[0] if stack else None
            if not (top is not None and top.virtual and top.key == family):
                close(1, at)
                node = _Node(family, 1, at, virtual=True)
                roots.append(node)
                stack.append(node)
            close(2, at)
            child = _Node(ident, 2, at)
            stack[-1].children.append(child)
            stack.append(child)
            continue
        depth = _depth_of(kind, ident)
        close(depth, at)
        node = _Node(_label_of(kind, ident), depth, at)
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    while stack:
        stack.pop().end = n_lines
    return roots


def _unique(used: set[str], base: str, page: int) -> str:
    """A heading id that repeats (a family seen again, a running header read as a heading) gets its page, then a count: ids are unique."""
    cid = base
    if cid in used:
        cid = f"{base} (p.{page})"
    n = 2
    while cid in used:
        cid = f"{base} (p.{page}) #{n}"
        n += 1
    used.add(cid)
    return cid


# ---------------------------------------------------------------- parts


def _size(lines: tuple[str, ...], lo: int, hi: int) -> int:
    return sum(len(x) + 1 for x in lines[lo:hi])


def _split(lines: tuple[str, ...], page_of: tuple[int, ...], lo: int, hi: int, max_chars: int, overlap: int) -> list[tuple[int, int, int]]:
    """Cut lines[lo:hi] into parts of at most `max_chars` of their own text (the repeated tail is added to the part after the first and may
    take it a little over): at the last PAGE END inside the limit, else at a line start. Returns (line_from, line_to, tail_chars)."""
    out: list[tuple[int, int, int]] = []
    start = lo
    while start < hi:
        used, end, page_end = 0, start, None
        while end < hi and (used + len(lines[end]) + 1 <= max_chars or end == start):
            used += len(lines[end]) + 1
            end += 1
            if end < hi and page_of[end] != page_of[end - 1]:
                page_end = end
        if end < hi and page_end is not None and page_end > start:
            end = page_end  # prefer the last page end inside the limit
        out.append((start, end, overlap if out else 0))
        start = end
    return out


def _chapter(book_id: str, cid: str, lines, page_of, lo: int, hi: int, depth: int, cut_by: str, max_chars: int, title_line: int):
    chars = _size(lines, lo, hi)
    spans = [(lo, hi, 0)] if chars <= max_chars else _split(lines, page_of, lo, hi, max_chars, OVERLAP_CHARS)
    parts = []
    for k, (a, b, tail) in enumerate(spans, 1):
        body = "\n".join(lines[a:b])
        if k > 1 and tail:
            pa, pb, _ = spans[k - 2]
            body = "\n".join(lines[pa:pb])[-tail:] + "\n" + body
        parts.append(ChapterPart(k, len(spans), page_of[a], page_of[b - 1], len(body), _sha(body)))
    chapter = Chapter(book_id, cid, title_line, depth, page_of[lo], page_of[hi - 1], chars, tuple(parts), cut_by)  # type: ignore[arg-type]
    return chapter, tuple(spans)


# ---------------------------------------------------------------- the cut


def cut(book_id: str, pages: list[tuple[int, str]], *, max_tokens: int = CLAUDE_CALL_TOKENS) -> CutBook:
    """The chapters of one book. `pages`: [(page number, stored text)] in page order, empty pages left out by the caller."""
    from . import subject_scope

    pages = [(int(n), t or "") for n, t in pages if (t or "").strip()]
    max_chars = max(1, int(max_tokens)) * CHARS_PER_TOKEN
    if not pages:
        return CutBook(book_id, (), 0, (), "heading", "no stored text", max_chars)
    raw: list[str] = []
    line_page: list[int] = []
    for n, text in pages:
        for line in text.splitlines():
            if line.strip():
                raw.append(line)
                line_page.append(n)
    lines, page_of = tuple(raw), tuple(line_page)
    st = subject_scope.StandardText(pages)
    heads = [h for h in st.heads]
    first = next((i for i, h in enumerate(heads) if h is not None), None)
    if first is None:
        return _windows(book_id, pages, lines, page_of, max_chars)
    roots = _tree(heads, len(lines))
    ids: set[str] = set()
    chapters: list[Chapter] = []
    spans: dict[str, tuple[tuple[int, int, int], ...]] = {}

    def emit(node: _Node, lo: int, hi: int) -> None:
        if hi <= lo:
            return
        cid = _unique(ids, node.key, page_of[lo])
        chapter, sp = _chapter(book_id, cid, lines, page_of, lo, hi, node.depth, "heading", max_chars, node.line)
        chapters.append(chapter)
        spans[cid] = sp

    def walk(node: _Node, lo: int) -> None:
        """Node's own span is [lo, node.end). Fits: one chapter. Else its sub-headings, the lead-in text joining the first one."""
        if _size(lines, lo, node.end) <= max_chars or not node.children:
            emit(node, lo, node.end)
            return
        kids = [c for c in node.children if c.line < node.end]
        if kids[0].line > lo:  # the lead-in text before the first sub-heading belongs to the first sub-heading's chapter
            walk(kids[0], lo)
        else:
            walk(kids[0], kids[0].line)
        for kid in kids[1:]:
            walk(kid, kid.line)

    for root in roots:
        walk(root, root.line)
    chapters, spans, covers = _join_small(book_id, chapters, spans, lines, page_of, max_chars)
    front = _size(lines, 0, first)
    front_pages = tuple(sorted({page_of[i] for i in range(first)}))
    return CutBook(book_id, tuple(chapters), front, front_pages, "heading", None, max_chars, lines, page_of, spans, covers)


def _join_small(book_id, chapters, spans, lines, page_of, max_chars):
    """Join runs of consecutive chapters that are each under `MIN_CHAPTER_CHARS` into one unit while it stays under the call limit.
    The unit is named "<first id> to <last id>" and keeps every heading it holds in `covers`; its text is the lines of all of them."""
    out: list[Chapter] = []
    out_spans: dict[str, tuple[tuple[int, int, int], ...]] = {}
    covers: dict[str, tuple[str, ...]] = {}
    run: list[Chapter] = []

    def flush() -> None:
        if not run:
            return
        if len(run) == 1:
            c = run[0]
            out.append(c)
            out_spans[c.chapter_id] = spans[c.chapter_id]
            covers[c.chapter_id] = (c.chapter_id,)
        else:
            lo = spans[run[0].chapter_id][0][0]
            hi = spans[run[-1].chapter_id][-1][1]
            cid = f"{run[0].chapter_id} to {run[-1].chapter_id}"
            c, sp = _chapter(book_id, cid, lines, page_of, lo, hi, min(r.depth for r in run), "heading", max_chars, run[0].title_line)
            out.append(c)
            out_spans[cid] = sp
            covers[cid] = tuple(r.chapter_id for r in run)
        run.clear()

    for c in chapters:
        if c.chars >= MIN_CHAPTER_CHARS or len(c.parts) > 1:  # a chapter of its own size stands alone
            flush()
            run.append(c)
            flush()
            continue
        if run and sum(r.chars for r in run) + c.chars > max_chars:
            flush()
        run.append(c)
        if sum(r.chars for r in run) >= MIN_CHAPTER_CHARS:
            flush()
    flush()
    return out, out_spans, covers


def _windows(book_id: str, pages: list[tuple[int, str]], lines, page_of, max_chars: int) -> CutBook:
    """No heading found: windows of `WINDOW_PAGES` pages with `WINDOW_REPEAT` page repeated; the id says the pages."""
    numbers = [n for n, _ in pages]
    chapters: list[Chapter] = []
    spans: dict[str, tuple[tuple[int, int, int], ...]] = {}
    step = max(1, WINDOW_PAGES - WINDOW_REPEAT)
    at = 0
    while at < len(numbers):
        window = numbers[at : at + WINDOW_PAGES]
        lo = next(i for i, p in enumerate(page_of) if p == window[0])
        hi = max(i for i, p in enumerate(page_of) if p == window[-1]) + 1
        cid = f"pages {window[0]}-{window[-1]}"
        chapter, sp = _chapter(book_id, cid, lines, page_of, lo, hi, 1, "page window", max_chars, lo)
        chapters.append(chapter)
        spans[cid] = sp
        if at + WINDOW_PAGES >= len(numbers):
            break
        at += step
    covers = {c.chapter_id: (c.chapter_id,) for c in chapters}
    return CutBook(book_id, tuple(chapters), 0, (), "page window", "no headings found: read by page windows", max_chars, lines, page_of, spans, covers)
