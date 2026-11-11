"""Quote-level OCR confidence for the rule labels (lifted from the lab labeller, exp12 b29b84d0, with its tests).

A page of a standard read by OCR (recognised text) carries one confidence per page in the app's own tables, and one weak
box anywhere says nothing about a quote elsewhere on the page. WHEN THE DATABASE HOLDS THE BOXES (`ocr_box`: one row per
recognised box with its score; `ocr_box_page`: one row per stored page), the confidence of a QUOTE is the MINIMUM score
of the boxes its words touch (`align_quote`), and the quote is low when that is unknown or under
`settings.ocr_low_conf_threshold`. Unknown = low: no boxes for the page, the quote's words not found in them exactly, or a
touched box without a score.

THE ALIGNMENT IS EXACT INSIDE THE QUOTE. A different sign, comparator, percent, degree, bracket, decimal mark, unit case
or letter inside the quote's own span means no alignment; only plain sentence punctuation at the OUTER edges of the whole
quote may differ. A word broken by a hyphen at the end of a box is one word standing in both boxes. A quote that stands
twice gets the lowest of its places.

THIS MODULE ONLY READS. The boxes must have been stored at OCR time; nothing here runs OCR. A database with no box table
keeps the strict page rule: a recognised page whose own lowest confidence is unknown or under the threshold is low. A
page with no origin row has an unknown source and needs box evidence too.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import rule_labels

Box = tuple[str, "float | None"]

#: Plain sentence punctuation that may differ at the OUTER edges of the whole quote (and only there).
_OUTER = "\"'()[]{}.,;:" + "\u201c\u201d\u2018\u2019"


def has_boxes_table(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ocr_box'"
        ).fetchone()
        is not None
        and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ocr_box_page'"
        ).fetchone()
        is not None
    )


def load_boxes(conn, sdid: str, page: int) -> list[Box]:
    """The stored boxes of a page in reading order, or [] (no row for the page). Boxes of a page whose re-read text
    differs from the stored page text are used too, but only through `align_quote`, which needs the quote's own words to
    stand in them exactly."""
    if (
        conn.execute(
            "SELECT 1 FROM ocr_box_page WHERE document_id = ? AND page_no = ?",
            (sdid, int(page)),
        ).fetchone()
        is None
    ):
        return []
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT text, score FROM ocr_box WHERE document_id = ? AND page_no = ? ORDER BY seq",
            (sdid, int(page)),
        )
    ]


def _page_words(boxes: Sequence[Box]) -> list[tuple[str, frozenset[int]]]:
    """(word, indexes of the boxes it stands in) for every whitespace-separated word of the page, in reading order; a
    word broken by a hyphen at the end of a box and finished in the next is ONE word standing in both boxes."""
    words: list[tuple[str, frozenset[int]]] = []
    toks = [str(t).split() for t, _ in boxes]
    skip: set[tuple[int, int]] = set()
    for i, ts in enumerate(toks):
        for j, w in enumerate(ts):
            if (i, j) in skip:
                continue
            if (
                j == len(ts) - 1
                and len(w) > 1
                and w.endswith("-")
                and w[-2].isalpha()
                and i + 1 < len(toks)
                and toks[i + 1]
                and toks[i + 1][0][:1].isalpha()
            ):
                words.append((w[:-1] + toks[i + 1][0], frozenset({i, i + 1})))
                skip.add((i + 1, 0))
                continue
            words.append((w, frozenset({i})))
    return words


def _same_word(page_word: str, q_word: str, first: bool, last: bool) -> bool:
    """INSIDE the quote a word must match exactly (digits, decimal marks, signs, comparators, %, degree, unit letters,
    "not", case). Only the OUTER edge of the whole quote may differ by plain sentence punctuation."""
    if page_word == q_word:
        return True
    pw, qw = page_word, q_word
    if first:
        pw, qw = pw.lstrip(_OUTER), qw.lstrip(_OUTER)
    if last:
        pw, qw = pw.rstrip(_OUTER), qw.rstrip(_OUTER)
    return bool(qw) and pw == qw


def align_quote(quote: str | None, boxes: Sequence[Box]) -> float | None:
    """The MINIMUM score over the boxes the quote touches (over every place the quote stands, the lowest), or None when
    unknown: no boxes, the quote is not found in their words, or a touched box has no score."""
    if not boxes or not str(quote or "").strip():
        return None
    q = [w for w in re.sub(r"-\s+", "", str(quote)).split() if w]
    words = _page_words(boxes)
    if not q or len(q) > len(words):
        return None
    best: float | None = None
    for i in range(len(words) - len(q) + 1):
        if all(
            _same_word(words[i + k][0], q[k], k == 0, k == len(q) - 1)
            for k in range(len(q))
        ):
            touched = set().union(*(words[i + k][1] for k in range(len(q))))
            scores = [boxes[b][1] for b in touched]
            if any(s is None for s in scores):
                return None
            low = min(float(s) for s in scores)
            best = low if best is None else min(best, low)
    return best


def quote_is_low(
    conn, sdid: str, page: int | None, quote: str | None, origin: Mapping | None
) -> bool:
    """Whether the quote may not be approved for the quality of its text. `origin` is the page's entry of
    `compiled_rule_report.page_origin` (None: no entry, the source is unknown). A text-layer ('native') page is never
    low. Any other page: with the box table in this database, the quote-level rule above; without it, the strict page
    rule (`rule_labels.page_is_low_confidence_ocr`, and an unknown source is low)."""
    from .config import settings

    source = (origin or {}).get("page_source")
    if source == "native":
        return False
    if page is not None and has_boxes_table(conn):
        conf = align_quote(quote, load_boxes(conn, sdid, page))
        return conf is None or conf < float(settings.ocr_low_conf_threshold)
    return source != "recognised" or rule_labels.page_is_low_confidence_ocr(origin)
