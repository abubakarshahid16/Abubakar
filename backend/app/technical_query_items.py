"""A contractor's request of MANY numbered items is searched ONE ITEM AT A TIME (lead-4's blind test of seven of the owner's approved
answers, 27 Nov 2026: 1 of 7 drafts matched; the dominant cause was one search for the whole list, so every item's own subject was
diluted and a real held answer was buried). The whole question is still searched once (the form's own citations, the coverage line);
then each item gets its own search, and its best passages are listed with the item's number, before the rest. The draft then takes the
passages item by item (technical_query_auto.draft_passages). Local search only; nothing leaves the machine.
"""

from __future__ import annotations

import re
from typing import Any

#: A line that starts a numbered or lettered item: "1.", "2)", "(3)", "a.", "(b)".
_ITEM_START = re.compile(r"^\s*\(?(\d{1,2}|[a-hA-H])[.)]\s+(?=\S)")
#: Per item, its best passages listed before the rest.
PER_ITEM = 3
#: At most this many items are searched one by one (a longer list: the rest are covered by the whole-question search, and counted).
MAX_ITEMS = 12


def items_of(question: str) -> list[str]:
    """The numbered items of a request, each with its wrapped continuation lines (a blank line ends an item); [] when fewer than two."""
    items: list[str] = []
    open_item = False
    for line in (question or "").splitlines():
        if _ITEM_START.match(line):
            items.append(_ITEM_START.sub("", line, count=1).strip())
            open_item = True
        elif not line.strip():
            open_item = False
        elif open_item and len(items[-1]) < 2000:
            items[-1] = f"{items[-1]} {line.strip()}"
    return items if len(items) >= 2 else []


def search(
    question: str, allowed: frozenset[str], progress, form_texts: list[str]
) -> dict[str, Any]:
    """`technical_query_contracts.search_all`'s shape: the whole question's search, and, for a request of several items, each item's own
    best PER_ITEM passages first, tagged `item` (1-based), the same passage never twice. The coverage line says how many items were
    searched one by one."""
    from . import technical_query_contracts as tqc

    whole = tqc.search_all(question, allowed, progress, form_texts)
    items = items_of(question)
    if not items:
        return whole
    hits = whole.get("hits") or []
    cited = [h for h in hits if h.get("cited")]
    seen = {_key(h) for h in cited}
    per_item: list[dict[str, Any]] = []
    for n, item in enumerate(items[:MAX_ITEMS], 1):
        if progress:
            progress(
                n - 1,
                min(len(items), MAX_ITEMS),
                f"searching item {n} of {min(len(items), MAX_ITEMS)}",
            )
        found = tqc.search_all(item, allowed, None, None).get("hits") or []
        taken = 0
        for hit in found:
            if taken >= PER_ITEM:
                break
            if hit.get("cited") or _key(hit) in seen:
                continue
            seen.add(_key(hit))
            per_item.append({**hit, "item": n})
            taken += 1
    rest = [h for h in hits if not h.get("cited") and _key(h) not in seen]
    coverage = dict(whole.get("coverage") or {})
    searched = min(len(items), MAX_ITEMS)
    note = f" The {searched} numbered items were also searched one by one."
    if len(items) > MAX_ITEMS:
        note += f" {len(items) - MAX_ITEMS} more items were covered by the search of the whole request only."
    coverage["line"] = (coverage.get("line") or "") + note
    coverage["items"] = len(items)
    return {**whole, "hits": cited + per_item + rest, "coverage": coverage}


def _key(hit: dict[str, Any]) -> tuple:
    return (
        hit.get("document_id"),
        hit.get("page_start"),
        (hit.get("text") or "")[:200],
    )
