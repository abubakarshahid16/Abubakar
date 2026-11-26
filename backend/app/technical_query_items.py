"""A contractor's request of MANY numbered items is searched ONE ITEM AT A TIME (lead-4's blind test of seven of the owner's approved
answers, 27 Nov 2026: 1 of 7 drafts matched; the dominant cause was one search for the whole list, so every item's own subject was
diluted and a real held answer was buried). The whole question is still searched once (the form's own citations, the coverage line);
then each item gets its own search, and its best passages are listed with the item's number, before the rest. The draft then takes the
passages item by item (technical_query_auto.draft_passages). Local search only; nothing leaves the machine.
"""

from __future__ import annotations

import re
from typing import Any

#: The ONE item marker of a request's list, shared with the question extractor (technical_query_mail._ITEM) so the two never disagree
#: (fresh review of PR #1936: the extractor kept "i) ii) iii)" items that this splitter did not split): a number ("1.", "2)", "(3)"),
#: a letter a-h, a roman numeral i-xii in either case, or a bullet ("-", "*", the bullet sign).
ITEM_MARK = (
    r"(?:\(?(?:\d{1,2}|[a-hA-H]|(?i:ix|iv|v?i{1,3}|v|x|xi{1,2}))[.)]|[-\u2022*])"
)
_ITEM_START = re.compile(rf"^\s*{ITEM_MARK}\s+(?=\S)")
#: An item's own text, wrapped lines included, is cut past this with a visible mark (never silently).
ITEM_CAP = 2000
ITEM_CUT = " [cut here: the rest of this item is in the request]"
#: The version of the evidence SEARCH, stamped on each preparation (technical_queries.evidence_search_version), like a draft's
#: prompt version: 1 = one search for the whole request; 2 = each numbered item searched on its own (o14 update 21); 3 = each item
#: searched with its request's lead line. Evidence from an older search is marked out of date, the page offers "Find the sources
#: again", and the next server start searches it again by itself (lead-4, 27 Nov 2026).
SEARCH_VERSION = 3
#: The whole request's own best passages, always listed (before the items'), whatever the number of items.
WHOLE_BEST = 3
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
        elif open_item and not items[-1].endswith(ITEM_CUT):
            joined = f"{items[-1]} {line.strip()}"
            items[-1] = (
                joined
                if len(joined) <= ITEM_CAP
                else joined[:ITEM_CAP].rstrip() + ITEM_CUT
            )
    return items if len(items) >= 2 else []


#: How much of the request's lead line goes with each item's search (search text only, never shown).
LEAD_CHARS = 300


def lead_of(question: str) -> str:
    """The request's lead line: the paragraph just before its numbered list ("Please confirm which of the following positions shall
    apply to <the subject>:"), at most LEAD_CHARS (cut at a word). It carries the SUBJECT an item's own words may lack (lead-4's
    re-score, 27 Nov 2026: an option "Position 1: handled as ..." searched alone found a higher-scoring, unrelated contract clause)."""
    lines = (question or "").splitlines()
    first = next((n for n, line in enumerate(lines) if _ITEM_START.match(line)), None)
    if not first:
        return ""
    paragraphs = [
        p.strip() for p in "\n".join(lines[:first]).split("\n\n") if p.strip()
    ]
    lead = " ".join(paragraphs[-1].split()) if paragraphs else ""
    return lead if len(lead) <= LEAD_CHARS else lead[:LEAD_CHARS].rsplit(" ", 1)[0]


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
    # the WHOLE request's own best passages are always listed, right after the form's citations, so the items' lists never crowd
    # them out (F's live redo, 27 Nov 2026: 21 item passages filled the listing and cut the whole request's best, the very passages
    # its earlier draft rested on)
    whole_best = [h for h in hits if not h.get("cited")][:WHOLE_BEST]
    seen = {_key(h) for h in cited + whole_best}
    per_item: list[dict[str, Any]] = []
    for n, item in enumerate(items[:MAX_ITEMS], 1):
        if progress:
            progress(
                n - 1,
                min(len(items), MAX_ITEMS),
                f"searching item {n} of {min(len(items), MAX_ITEMS)}",
            )
        # each item is searched WITH its lead line, so the search carries the request's subject
        found = (
            tqc.search_all(
                f"{lead_of(question)} {item}".strip(), allowed, None, None
            ).get("hits")
            or []
        )
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
    return {**whole, "hits": cited + whole_best + per_item + rest, "coverage": coverage}


def _key(hit: dict[str, Any]) -> tuple:
    return (
        hit.get("document_id"),
        hit.get("page_start"),
        (hit.get("text") or "")[:200],
    )
