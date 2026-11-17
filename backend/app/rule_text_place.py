"""WHERE A RULE'S TEXT SITS IN ITS BOOK decides whether it can be a requirement at all (order 14, W-D7, 17 Nov 2026).

A contents entry ("8 Application Requirements ..... 12") or an entry of a book's reference list ("API 999 Pumps; ISO 12345 Valves") names
a topic or another book. It obliges nothing, so it is never the rule a paper is checked against. ONE function decides it
(`not_a_requirement`), from where the text sits, never from a book's own spelling (CLAUDE.md rule 13):

  the chunk         the library's own reading of the book marks the chunk the text came from as a contents or index chunk (kind
                    `toc` / `index`) or a reference-list chunk (kind `references`), or it sits under a contents or reference-list
                    heading (its section label or heading chain; the headings live in `reference/front_matter.json`).
  the page          a quote the reader took from a book page is looked up on that page: every chunk of the page that holds it is a
                    contents or index chunk.
  the text alone    a reference-list heading ("References", "Normative references", "Bibliography") opens a part of the text and
                    the text cites at least `MIN_CITATIONS` other standards (`standard_ids.find_citations`).

A REAL REQUIREMENT IS NEVER LOST: a text that holds a requirement word ("shall", "must", "should", "required", a limit word) is a
requirement wherever it sits, so none of the three tests applies to it (lead, review of PR #1889). Reads only; no model, no network. Shared with the procedure
review (scope and definition clauses are the same family: `not_a_requirement` is the one home to extend).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CONTENTS = "a contents entry"
REFERENCE_LIST = "a reference-list entry"
#: The chunk kinds the library gives a contents page, an index and a reference list (`chunker`).
_KIND_PLACE = {"toc": CONTENTS, "index": CONTENTS, "references": REFERENCE_LIST}
MIN_CITATIONS = 2
#: A requirement word: a text holding one is a requirement wherever it sits (never lost). Broad on purpose: a false "requirement" only
#: keeps a row; a false "not a requirement" would drop one.
_REQUIREMENT_WORD = re.compile(
    r"\b(?:shall|must|should|required|requires?|requirement\s+is|is\s+to\s+be|are\s+to\s+be|has\s+to|have\s+to|needs?\s+to|may\s+not|"
    r"not\s+permitted|prohibited|minimum|maximum|at\s+least|at\s+most|not\s+exceed|not\s+less\s+than|not\s+more\s+than|limited\s+to)\b",
    re.IGNORECASE,
)
_NUMBERING = re.compile(r"^\s*(?:[A-Z]|\d+(?:\.\d+)*)[.)]?\s+")
VOCABULARY_PATH = Path(__file__).parent / "reference" / "front_matter.json"


@lru_cache(maxsize=1)
def _headings() -> tuple[frozenset[str], frozenset[str]]:
    """(the contents headings, the reference-list headings), lower case, from the editable vocabulary."""
    data = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    contents = frozenset(
        h.strip().lower() for h in data.get("contents_headings") or [] if h.strip()
    )
    refs = frozenset(
        h.strip().lower()
        for h in data.get("reference_list_headings") or []
        if h.strip()
    )
    return contents, refs


@lru_cache(maxsize=1)
def _reference_heading_in_text() -> re.Pattern | None:
    """A reference-list heading written with a capital inside a text (case-sensitive: "the references below" is not a heading)."""
    words = sorted(
        {h.title() for h in _headings()[1]}
        | {h[:1].upper() + h[1:] for h in _headings()[1]},
        key=len,
        reverse=True,
    )
    return (
        re.compile(
            r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in words) + r")(?![\w-])"
        )
        if words
        else None
    )


def is_requirement_text(text) -> bool:
    """Does the text hold a requirement word? Such a text is a requirement wherever it sits."""
    return bool(_REQUIREMENT_WORD.search(str(text or "")))


def _heading_place(heading) -> str | None:
    name = _NUMBERING.sub("", str(heading or "")).strip().rstrip(":.").lower()
    contents, refs = _headings()
    if name in contents:
        return CONTENTS
    return REFERENCE_LIST if name in refs else None


def place_of_chunk(kind=None, section=None, context=None) -> str | None:
    """What a chunk is by where it sits: its kind, else its section label or any heading of its heading chain."""
    if kind in _KIND_PLACE:
        return _KIND_PLACE[kind]
    chain = [p for p in re.split(r"\s*>\s*", str(context or "")) if p]
    return next(
        (pl for h in [section, *chain] if h and (pl := _heading_place(h))), None
    )


def place_of_text(text) -> str | None:
    """A reference-list entry recognised from the text alone: a reference-list heading stands in it, it cites at least
    `MIN_CITATIONS` other standards and it holds no requirement word."""
    from .standard_ids import find_citations

    text = str(text or "")
    pattern = _reference_heading_in_text()
    if is_requirement_text(text) or not (pattern and pattern.search(text)):
        return None
    return REFERENCE_LIST if len(find_citations(text)) >= MIN_CITATIONS else None


def _fold(text) -> str:
    return " ".join(str(text or "").split()).lower()


def place_on_page(conn, book_id, page, quote) -> str | None:
    """A quote taken from a book page: what it is when EVERY chunk of that page holding it is a contents or index chunk."""
    q = _fold(quote)
    if not (book_id and q and isinstance(page, int)):
        return None
    rows = conn.execute(
        "SELECT kind, section, context, text FROM chunks WHERE document_id = ? AND page_start <= ? AND page_end >= ?",
        (book_id, page, page),
    ).fetchall()
    holding = [r for r in rows if q in _fold(r["text"])]
    places = {place_of_chunk(r["kind"], r["section"], r["context"]) for r in holding}
    return places.pop() if holding and len(places) == 1 and None not in places else None


def place_of_requirement(conn, requirement_id) -> str | None:
    """Where a stored rule's text sits: its chunk (kind, heading), else its own text."""
    if not requirement_id:
        return None
    r = conn.execute(
        "SELECT r.requirement_text, r.source_text, c.kind, c.section, c.context FROM standard_requirements r"
        " LEFT JOIN chunks c ON c.id = r.chunk_id WHERE r.id = ?",
        (requirement_id,),
    ).fetchone()
    if r is None:
        return None
    return not_a_requirement(
        r["source_text"] or r["requirement_text"],
        chunk=(r["kind"], r["section"], r["context"]),
    )


def not_a_requirement(
    text, *, chunk=None, conn=None, book_id=None, page=None
) -> str | None:
    """THE decision (W-D7): what the text is when it is a contents entry or a reference-list entry, else None. A text holding a
    requirement word is never one (no real requirement is lost). `chunk` (kind, section, context) is where the library stored it;
    with `conn`, `book_id` and `page`, the quote is looked up on its book page."""
    if not str(text or "").strip() or is_requirement_text(text):
        return None
    if chunk and (place := place_of_chunk(*chunk)):
        return place
    if conn is not None and (place := place_on_page(conn, book_id, page, text)):
        return place
    return place_of_text(text)


# TEST HOOK: a test that edits the vocabulary starts from a clean state; the app does not call it.
def reload_vocabulary() -> None:
    _headings.cache_clear()
    _reference_heading_in_text.cache_clear()
