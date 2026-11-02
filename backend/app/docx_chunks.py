"""Chunks for a Word document, built from its STRUCTURE (W5b-01, #525).

A PDF is chunked by guessing structure from text (running headers, clause
numbers, page classes). A Word document states its structure, so nothing is
guessed here: a chunk never crosses a heading, a table is cut only on row
boundaries with its header row repeated, and every chunk knows where it sits:

  * `locator`  "4.2 > para 3", "4.2 > para 3-5", "4.2 > table 1": the heading
    path plus the paragraph or table number inside the innermost section. This
    is what a citation shows instead of a page number (Word has no fixed pages).
  * `section`  the innermost heading, "4.2 Pipes larger than 2 inch".
  * `context`  the full heading chain (index text, never quoted).

Same chunk shape and the same sizes as a PDF chunk (`chunker.Block`, the same
token target and ceiling), so search, embedding, requirements and reviews read
a Word chunk exactly like a PDF one.

KEPT BESIDE THE BODY, never in it: headers and footers, tracked changes (the
deleted and the inserted text), comments and the table of contents become
chunks of their own kinds (`header_footer`, `tracked_change`, `comment`,
`toc`). They are stored and inspectable and are NOT retrievable
(`chunker.RETRIEVABLE_KINDS` is prose and table only), so a footer is never
quoted as body text and deleted text is never quoted as current text.
"""
from __future__ import annotations

from . import chunker
from .chunker import Block, count_tokens
from .config import settings
from .docx_pages import PAGES_NONE, PAGES_PARTIAL
from .docx_reader import (
    FURNITURE_COMMENT,
    FURNITURE_FOOTER,
    FURNITURE_HEADER,
    FURNITURE_TOC,
    FURNITURE_TRACKED,
    KIND_HEADING,
    KIND_TABLE,
    DocBlock,
    Structure,
    block_lines,
)

HEADER_FOOTER_KIND = "header_footer"
TRACKED_KIND = "tracked_change"
COMMENT_KIND = "comment"
TOC_KIND = "toc"

#: Appended to the locator of a chunk whose text carries a tracked insertion.
TRACKED_SUFFIX = " (contains a tracked change)"

_FURNITURE_KIND = {
    FURNITURE_HEADER: HEADER_FOOTER_KIND, FURNITURE_FOOTER: HEADER_FOOTER_KIND,
    FURNITURE_TRACKED: TRACKED_KIND, FURNITURE_COMMENT: COMMENT_KIND, FURNITURE_TOC: TOC_KIND,
}


class _Heading(str):
    """A heading waiting for the block it is carried in with. `page`: its own page when
    the file has real pages, so a chunk starts where its first line is; None: as before."""

    page: int | None = None

    @classmethod
    def of(cls, text: str, page: int, structure: Structure) -> _Heading:
        heading = cls(text)
        pagination = structure.pagination
        heading.page = page if pagination and pagination.source != PAGES_NONE else None
        return heading


def _where(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def _para_range(first: int | None, last: int | None) -> str:
    if first is None:
        return ""
    return f"para {first}" if first == last else f"para {first}-{last}"


def _locator(path: tuple[str, ...], tail: str, tracked: bool) -> str:
    text = " > ".join(p for p in (_where(path), tail) if p) or "document start"
    return text + (TRACKED_SUFFIX if tracked else "")


def build_chunks(structure: Structure) -> list[Block]:
    """All chunks of one Word document, body first, furniture after."""
    target = settings.chunk_target_tokens
    ceiling = settings.chunk_max_tokens
    chunks: list[Block] = []

    lines: list[str] = []
    tokens = 0
    paras: list[int] = []
    pages: list[int] = []
    tracked = False
    pending_heading: str | None = None
    path: tuple[str, ...] = ()
    chain: tuple[str, ...] = ()

    def stamp(block: Block, tail: str, was_tracked: bool) -> Block:
        block.locator = _locator(path, tail, was_tracked)
        block.context = " > ".join(chain) if chain else None
        return block

    def flush() -> None:
        nonlocal lines, tokens, paras, pages, tracked, pending_heading
        if not lines:
            return
        text = "\n".join(lines).strip()
        if text:
            tail = _para_range(min(paras), max(paras)) if paras else ""
            pieces = ([Block("prose", text, min(pages), max(pages), chain[-1] if chain else None,
                             count_tokens(text))]
                      if count_tokens(text) <= ceiling
                      else chunker.split_oversized(text, min(pages), max(pages),
                                                   chain[-1] if chain else None, "prose"))
            for piece in pieces:
                chunks.append(stamp(piece, tail, tracked))
        lines, tokens, paras, pages, tracked = [], 0, [], [], False

    def add_line(block: DocBlock, line: str) -> None:
        nonlocal tokens, tracked, pending_heading
        t = count_tokens(line)
        if lines and tokens + t > target:
            flush()
        if pending_heading is not None:
            lines.append(pending_heading)
            tokens += count_tokens(pending_heading)
            pages.append(pending_heading.page or block.page)
            pending_heading = None
        lines.append(line)
        tokens += t
        if block.para_no is not None:
            paras.append(block.para_no)
        pages.append(block.page)
        tracked = tracked or block.tracked

    for b in structure.blocks:
        if b.kind == KIND_HEADING:
            flush()
            path, chain = b.path, b.chain
            pending_heading = _Heading.of(block_lines(b)[0], b.page, structure)
            continue
        if b.path != path:           # body text before the first heading
            flush()
            path, chain = b.path, b.chain
        if b.kind == KIND_TABLE:
            flush()
            chunks.extend(_table_chunks(b, path, chain, target, ceiling))
            pending_heading = None
            continue
        add_line(b, block_lines(b)[0])
    flush()

    for f in structure.furniture:
        kind = _FURNITURE_KIND[f.kind]
        label = {FURNITURE_HEADER: "[header] ", FURNITURE_FOOTER: "[footer] ",
                 FURNITURE_TRACKED: "[tracked change] ", FURNITURE_COMMENT: "[comment] ",
                 FURNITURE_TOC: "[table of contents] "}[f.kind]
        text = label + f.text
        pieces = ([Block(kind, text, f.page, f.page, None, count_tokens(text))]
                  if count_tokens(text) <= ceiling
                  else chunker.split_oversized(text, f.page, f.page, None, kind))
        for piece in pieces:
            piece.locator = f.locator
            chunks.append(piece)
    return _stamp_real_pages(chunks, structure)


def _stamp_real_pages(chunks: list[Block], structure: Structure) -> list[Block]:
    """A file with real pages (WORD_PAGE_MARKERS_ENABLED) is cited by page as well
    as by where it sits. No pages (or the switch off): the locator alone, as before."""
    pagination = structure.pagination
    if pagination is None or pagination.source == PAGES_NONE:
        return chunks
    said = " (page marks partial)" if pagination.source == PAGES_PARTIAL else ""
    for c in chunks:
        if c.kind in ("prose", "table"):
            first, last = c.page_start, c.page_end or c.page_start
            where = f"page {first}" if first == last else f"pages {first}-{last}"
            c.locator = f"{where}{said}, {c.locator}" if c.locator else f"{where}{said}"
    return chunks


def _table_chunks(b: DocBlock, path: tuple[str, ...], chain: tuple[str, ...], target: int,
                  ceiling: int) -> list[Block]:
    rows = [list(r) for r in b.rows]
    width = max(len(r) for r in rows)
    header, data = chunker._table_header(rows)
    lead = [chunker._md_row(header, width)] if header else []
    md_rows = [chunker._md_row(r, width) for r in data]
    section = chain[-1] if chain else None
    # A table over several real pages: each row keeps its page (a folded header
    # is the first rows, so the data rows are the last ones).
    row_pages = (
        b.row_pages[-len(md_rows) :]
        if b.row_pages and md_rows
        else [b.page] * len(md_rows)
    )
    whole = Block(
        "table",
        "\n".join(lead + md_rows),
        b.page,
        max(row_pages, default=b.page),
        section,
        0,
        lead=lead,
        rows=md_rows,
        row_pages=row_pages,
        header=tuple(header) if header else None,
    )
    whole.tokens = count_tokens(whole.text)
    pieces = chunker._split_structured(whole, target, ceiling)
    tail = f"table {b.table_no}"
    for piece in pieces:
        piece.locator = _locator(path, tail, b.tracked)
        piece.context = " > ".join(chain) if chain else None
        piece.section = section
    return pieces
