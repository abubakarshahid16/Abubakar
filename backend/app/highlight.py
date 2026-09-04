"""Locating a quoted answer on the rendered page.

The single most convincing thing this product does: an engineer sees the
answer outlined on the actual specification page. Reading a quotation asks
them to trust the extraction; seeing it boxed on the page they know asks them
to trust nothing at all.

PyMuPDF's page.search_for() does the work. The difficulty is that the text we
quote is not the text on the page: extraction normalised whitespace, dropped
symbol-font characters, joined hyphenated line breaks, and the chunk may have
been assembled across a page boundary. A verbatim search therefore misses
often, and the fallbacks are progressively shorter fragments of the same span.

WHAT THIS MUST NEVER DO IS BOX THE WRONG PLACE. Every fallback narrows the
search to a SHORTER piece of the SAME text; none of them substitutes different
text or relaxes into approximate matching. When nothing is found the caller is
told so and the page is shown without a box, because an engineer who once sees
a box around the wrong clause has no reason to trust any box again.
"""

from __future__ import annotations

import re

import fitz

#: Below this many characters a fragment is too generic to locate safely.
#: "3" or "of the" would match dozens of places on a specification page.
MIN_FRAGMENT_CHARS = 12

#: A page has to be pathological to need more than this, and each attempt
#: costs a full-page text search.
MAX_ATTEMPTS = 8

#: Rectangles covering more than this fraction of the page are not a
#: highlight, they are the page. Something matched far too loosely.
MAX_COVERAGE = 0.6

_WS = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _candidates(span_text: str) -> list[str]:
    """Progressively shorter fragments of the SAME text, longest first.

    Never a different string and never a looser match - only less of what was
    asked for. That is what keeps a miss a miss rather than a wrong box.
    """
    text = _WS.sub(" ", span_text).strip()
    if not text:
        return []

    out: list[str] = [text]

    # The first sentence: extraction damage is often in the tail.
    sentences = [s.strip() for s in _SENTENCE.split(text) if s.strip()]
    if len(sentences) > 1:
        out.append(sentences[0])

    # Leading clauses of the first sentence, cut at punctuation a PDF is
    # unlikely to have mangled.
    head = sentences[0] if sentences else text
    for cut in (":", ";", ","):
        if cut in head:
            out.append(head.split(cut)[0].strip())

    # Then simply fewer words, from the front.
    words = head.split()
    for take in (12, 8, 6, 4):
        if len(words) > take:
            out.append(" ".join(words[:take]))

    seen: set[str] = set()
    unique: list[str] = []
    for c in out:
        c = c.strip(" .,;:")
        if len(c) >= MIN_FRAGMENT_CHARS and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:MAX_ATTEMPTS]


def locate(
    pdf_path: str, page_no: int, span_text: str
) -> tuple[list[tuple[float, float, float, float]], str | None]:
    """Rectangles for `span_text` on a 1-based page, in PDF user space.

    Returns (rectangles, matched_fragment). An empty list means the span could
    not be located, which the caller must report rather than paper over.
    """
    fragments = _candidates(span_text)
    if not fragments:
        return [], None

    with fitz.open(pdf_path) as doc:
        if not 1 <= page_no <= doc.page_count:
            return [], None
        page = doc.load_page(page_no - 1)
        page_area = abs(page.rect.get_area()) or 1.0

        for fragment in fragments:
            try:
                found = page.search_for(fragment, quads=False)
            except Exception:  # noqa: BLE001 - a search failure is a miss
                continue
            if not found:
                continue

            area = sum(abs(r.get_area()) for r in found)
            if area / page_area > MAX_COVERAGE:
                # matched almost the whole page: not a highlight
                continue

            return (
                [(r.x0, r.y0, r.x1, r.y1) for r in found],
                fragment,
            )

    return [], None


def for_chunk(document_id: str, chunk_id: str, question: str) -> dict:
    """Locate the answering span for a chunk, given the question.

    Derived rather than stored, because the span depends on the question: the
    same passage highlights differently for two different questions. The
    passage is expanded exactly as the answer path expands it, and the span is
    found by the same function, so what is boxed is what was quoted.
    """
    from . import answer as answer_mod
    from . import passages as passages_mod
    from .db import connect

    row = connect().execute(
        """SELECT c.text, c.page_start, d.stored_path
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE c.id = ? AND c.document_id = ?""",
        (chunk_id, document_id),
    ).fetchone()
    if row is None:
        return {"rects": [], "located": False, "note": "unknown chunk"}

    expanded = passages_mod.expand_passage(chunk_id, document_id)
    text = expanded.get("text") or row["text"]
    span = answer_mod.find_answer_span(question, text)

    document = {"stored_path": row["stored_path"]}
    return rectangles_for_answer(
        document,
        expanded.get("page_start", row["page_start"]),
        text,
        list(span) if span else None,
    )


def rectangles_for_answer(
    document: dict, page_no: int, passage_text: str, highlight: list[int] | None
) -> dict:
    """Where the answering span sits on this page.

    `highlight` is the character span within `passage_text` that Tier 1
    identified as answering the question. When there is no span the whole
    passage is attempted, because the passage itself is the answer.
    """
    # A box means "here is the answer". With no identified answering span there
    # is no answer to point at, and boxing the whole passage instead produced
    # eleven rectangles covering most of the text - not a wrong box, but it
    # reads as "the answer is all of this", which is its own kind of untrue.
    if not (highlight and len(highlight) == 2):
        return {
            "page": page_no,
            "rects": [],
            "matched_fragment": None,
            "located": False,
            "note": "no single answering sentence could be identified, so no box is drawn",
        }

    start, end = highlight
    if not 0 <= start < end <= len(passage_text):
        return {
            "page": page_no,
            "rects": [],
            "matched_fragment": None,
            "located": False,
            "note": "the answering span does not fit the passage, so no box is drawn",
        }

    span = passage_text[start:end]
    rects, matched = locate(document["stored_path"], page_no, span)
    return {
        "page": page_no,
        "rects": rects,
        "matched_fragment": matched,
        "located": bool(rects),
        # Stated plainly, because the alternative to admitting a miss is
        # drawing a box somewhere plausible and wrong.
        "note": (
            None
            if rects
            else "the quoted text could not be located on this page, so no box is drawn"
        ),
    }
