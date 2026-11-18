"""A value belongs to the equipment item its section, block, table heading or sheet names (owner, 18 Nov 2026 after live: 5 of 7 WRONG
comments on one paper set a driver's value against the main item's). The judge names the item of each value and the second value
a comparison rests on; code checks them on the paper. When the two items are both found on their pages and differ, the line is
no finding: it stays in "All points" with the note `DIFFERENT_ITEMS` and is never sent. Anything code cannot verify changes
nothing. The item names come from the paper; no equipment word is written here."""

from __future__ import annotations

from . import DIFFERENT_ITEMS
from .verify import norm, quote_in

#: The code-note part when the judge named two items but code did not accept them (why, in fixed words; the line stays sent).
ITEMS_NOT_ACCEPTED = "items not accepted"
#: An item name shorter than this (folded) names nothing reliable.
ITEM_MIN = 3


def _item(words, page_text: str) -> str:
    """The item name folded, when it is long enough and stands on the page; else ""."""
    folded = norm(str(words or ""))
    return folded if len(folded) >= ITEM_MIN and folded in norm(page_text or "") else ""


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
    first = _item(items[0], paper.pages.get(d["page"], ""))
    second = _item(items[1], paper.pages.get(page2, ""))
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
