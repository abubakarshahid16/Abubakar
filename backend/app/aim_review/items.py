"""A value belongs to the equipment item its section, block, table heading or sheet names (owner, 18 Nov 2026 after live: 5 of 7 WRONG
comments on one paper set a driver's value against the main item's). The judge names the item of each value and the second value
a comparison rests on; code checks them on the paper. When the two items are both found on their pages and differ, the line is
no finding: it stays in "All points" with the note `DIFFERENT_ITEMS` and is never sent. Anything code cannot verify changes
nothing. The item names come from the paper; no equipment word is written here."""

from __future__ import annotations

import re

from . import DIFFERENT_ITEMS
from .verify import _squeeze, norm, quote_in

#: The code-note part when the judge named two items but code did not accept them (why, in fixed words; the line stays sent).
ITEMS_NOT_ACCEPTED = "items not accepted"
#: An item name shorter than this (folded) names nothing reliable.
ITEM_MIN = 3


#: Text runs on a line are apart when this many spaces or more stand between them (a form printed in two halves side by side).
_RUN = re.compile(r"\S+(?: {1,2}\S+)*")
#: A run that is only a line number or a clause reference: no part of a heading or a label.
_BARE = re.compile(r"^[\d.()/\s-]+$")
#: A clause reference inside a heading, such as "(7.1.5)": not part of the item's name.
_REF = re.compile(r"\(\s*[\d.\s]+\)")


def _runs(line: str) -> list[tuple[int, int, str]]:
    return [
        (m.start(), m.end(), m.group())
        for m in _RUN.finditer(line)
        if not _BARE.match(m.group())
    ]


def _heading_like(text: str) -> bool:
    """Capital words, mostly letters (a figure, a tag list or a unit is no heading), no fill, colon or star."""
    letters = [c for c in text if c.isalpha()]
    solid = [
        c for c in _REF.sub(" ", text) if not c.isspace()
    ]  # a clause reference is part of a heading
    return (
        len(letters) >= 4
        and all(c.isupper() for c in letters)
        and len(letters) >= 0.7 * len(solid)
        and not any(c in text for c in "_:*")
    )


def _headings(line: str) -> list[tuple[float, float, str]]:
    """(from position, to position, words) of each heading on a line: capital words with no fill, colon or star, not followed in
    the line by a fill-in (that is a field's label). A heading owns the line's positions half-way to its neighbours on the line."""
    runs = _runs(line)
    out = []
    for i, (start, end, text) in enumerate(runs):
        nxt = runs[i + 1][2] if i + 1 < len(runs) else ""
        if _heading_like(text) and not nxt.startswith(("_", "*")):
            left = (runs[i - 1][1] + start) / 2 if i else 0
            right = (end + runs[i + 1][0]) / 2 if i + 1 < len(runs) else float("inf")
            out.append((left, right, text))
    return out


def _place(page_text: str, quote: str) -> tuple[int, int] | None:
    """(line index, position on the line) where the quote starts on the page: the first line that holds the whole quote (folded)."""
    q = norm(quote)
    first = str(quote or "").split()[:1]
    if len(q) < ITEM_MIN or not first:
        return None
    for i, line in enumerate(page_text.split("\n")):
        if q in norm(line):
            col = line.lower().find(first[0].lower())
            return (i, col) if col >= 0 else None
    return None


def heading_of(page_text: str, quote: str) -> str:
    """The heading a value stands under: the nearest heading ABOVE the quote's line whose positions hold the quote's start (on a
    form printed in two halves side by side, the heading of the value's own half). Folded, clause references left out; ""
    when the quote's place or no heading is found."""
    lines = str(page_text or "").split("\n")
    where = _place(str(page_text or ""), quote)
    if where is None:
        return ""
    row, col = where
    for line in reversed(lines[:row]):
        for left, right, text in _headings(line):
            if left <= col < right:
                return norm(_REF.sub(" ", text))
    return ""


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[^\W\d_]{4,}", text)}


def _item(words, page_text: str, heading: str = "") -> str:
    """The item name folded, when it is long enough and stands on the page (spaces and hyphen breaks ignored, as for quotes),
    or shares a word with the heading code found above the value (a word's first six letters: "bearings" and "bearing");
    else ""."""
    folded = norm(str(words or ""))
    if len(folded) < ITEM_MIN:
        return ""
    page = norm(page_text or "")
    if folded in page or _squeeze(folded) in _squeeze(page):
        return folded
    return folded if _stems(heading) & _stems(folded) else ""


def check(d: dict, j: dict | None, paper) -> dict:
    """The decided line `d` of judgment `j`, with the note `DIFFERENT_ITEMS` added when the judgment rests on a second value
    ("other": page and quote) whose item differs from the first value's ("items": two names as the paper writes them), all of it
    verified on the pages. Never for a Met, nor a line code compared with a held rule (that comparison is code's own)."""
    if (
        not isinstance(j, dict)
        or d.get("label") == "Met"
        or d.get("page") is None
        or not d.get("quote")
    ):
        return d
    cmp_ = d.get("code_compare")
    if isinstance(cmp_, dict) and cmp_.get("read_from") != "verified paper quotes":
        return d
    other, items = j.get("other"), j.get("items")
    if not isinstance(other, dict) or not isinstance(items, list) or len(items) != 2:
        return d
    page2, quote2 = other.get("page"), str(other.get("quote") or "")
    if (
        not isinstance(page2, int)
        or isinstance(page2, bool)
        or not quote_in(quote2, paper.pages.get(page2, ""))
    ):
        return _unverified(d, "the second quote is not on its page")
    text1, text2 = paper.pages.get(d["page"], ""), paper.pages.get(page2, "")
    head1, head2 = heading_of(text1, d["quote"]), heading_of(text2, quote2)
    if (
        head1 and head1 == head2
    ):  # both values stand under one heading: one item, whatever the names
        return _unverified(d, "the same item: one heading above both values")
    first, second = _item(items[0], text1, head1), _item(items[1], text2, head2)
    if not first or not second:
        return _unverified(d, "an item name is not on its page")
    if first in second or second in first:
        return _unverified(d, "the same item")
    return _different(d, items, page2)


def _unverified(d: dict, why: str) -> dict:
    """The judge named the items, code did not accept them: the reason stays on the line (a record of the check; still sent)."""
    return {
        **d,
        "code": "; ".join(
            x for x in (d.get("code"), f"{ITEMS_NOT_ACCEPTED}: {why}") if x
        ),
    }


def _different(d: dict, items: list, page2: int) -> dict:
    note = (
        f'{DIFFERENT_ITEMS}: page {d["page"]} "{items[0]}" / page {page2} "{items[1]}"'
    )
    return {**d, "code": "; ".join(x for x in (d.get("code"), note) if x)}
