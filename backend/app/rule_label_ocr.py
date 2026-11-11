"""Quote-level OCR confidence for the rule labels (lifted from the lab labeller, exp12 b29b84d0, with its tests).

A page of a standard read by OCR (recognised text) carries one confidence per page in the app's own tables, and one weak
box anywhere says nothing about a quote elsewhere on the page. WHEN THE DATABASE HOLDS THE BOXES (`ocr_box`: one row per
recognised box with its score; `ocr_box_page`: one row per stored page), the confidence of a QUOTE is the MINIMUM score
of the boxes its words touch (`align_quote`), and the quote is low when that is unknown or under
`settings.ocr_low_conf_threshold`. Unknown = low: no boxes for the page, the quote's words not found in them exactly, or a
touched box without a score.

THE ALIGNMENT IS EXACT EVERYWHERE. Every word of the quote, the first and last included, must equal the box word: same
characters, same case (a different sign, comparator, percent, degree, bracket, decimal mark, unit case, letter or edge
punctuation means no alignment). The only normalisations, on both sides alike: whitespace runs collapsed, and a line-break
hyphen joined (letter, hyphen, whitespace, letter). A quote that stands twice gets the lowest of its places.

THIS MODULE ONLY READS. The boxes must have been stored at OCR time; nothing here runs OCR. A database with no box table
keeps the strict page rule: a recognised page whose own lowest confidence is unknown or under the threshold is low. A
page with no origin row has an unknown source and needs box evidence too.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import rule_labels

Box = tuple[str, "float | None"]


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


_BREAK = re.compile(r"(?<=[^\W\d_])-\s+(?=[^\W\d_])")


def _page_words(boxes: Sequence[Box]) -> list[tuple[str, frozenset[int]]]:
    """(word, indexes of the boxes it stands in) for every whitespace-separated word of the page, in reading order. The
    ONLY change to the words: a line-break hyphen inside a word (a word ending in "-" with a LETTER before the hyphen,
    followed by a word that starts with a LETTER, in the same box or the next) is joined into one word standing in both
    boxes. The quote side does exactly the same (`_BREAK`: letter, hyphen, whitespace, letter)."""
    flat = [(w, i) for i, (t, _) in enumerate(boxes) for w in str(t).split()]
    words: list[tuple[str, frozenset[int]]] = []
    k = 0
    while k < len(flat):
        w, i = flat[k]
        if (
            len(w) > 1
            and w.endswith("-")
            and w[-2].isalpha()
            and k + 1 < len(flat)
            and flat[k + 1][0][:1].isalpha()
        ):
            words.append((w[:-1] + flat[k + 1][0], frozenset({i, flat[k + 1][1]})))
            k += 2
            continue
        words.append((w, frozenset({i})))
        k += 1
    return words


def align_quote(quote: str | None, boxes: Sequence[Box]) -> float | None:
    """The MINIMUM score over the boxes the quote touches (over every place the quote stands, the lowest), or None when
    unknown: no boxes, the quote is not found in their words, or a touched box has no score. EVERY word of the quote,
    the first and the last included, must equal the box word exactly: the same characters in the same case. No edge
    stripping, no folding: a different character, sign, comparator, %, degree, bracket, case or edge punctuation means no
    alignment. The only normalisations, the same on both sides: whitespace runs collapsed and a line-break hyphen joined."""
    if not boxes or not str(quote or "").strip():
        return None
    q = _BREAK.sub("", str(quote)).split()
    words = _page_words(boxes)
    if not q or len(q) > len(words):
        return None
    best: float | None = None
    for i in range(len(words) - len(q) + 1):
        if all(words[i + k][0] == q[k] for k in range(len(q))):
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
