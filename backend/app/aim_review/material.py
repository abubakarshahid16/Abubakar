"""The clause material of the checklist build (S3 and the attack): each chosen book's rules, tagged for the equipment first then
by page, or the pages of a book that holds no stored rules; budgeted, every cut counted; and the batches S3 reads them in."""

from __future__ import annotations

import json
from collections import defaultdict

from . import library as L

MATERIAL_BUDGET = 150_000
BOOK_BUDGET = 45_000
TEXT_BOOK_BUDGET = 25_000
BATCH_CHARS = 50_000
RULE_CHARS = 700


def _dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def material(sel: dict, text: L.BookText) -> tuple[list[dict], list[dict]]:
    """The clause text S3 reads: each chosen book's rules (tagged for the equipment first, then by page), or the pages of a book
    that holds no stored rules. Budgeted, and every cut is counted (rows offered N of M)."""
    pool_by_book = defaultdict(list)
    for r in sel["_pool"]:
        pool_by_book[r["book"]].append(r)
    rows, stats, used, n = [], [], 0, 0
    for b in sel["books"]:
        mine = pool_by_book.get(b["book"], [])
        if b["chosen_subjects"] != "all":
            mine = [r for r in mine if r["subject"] in b["chosen_subjects"]]
        mine.sort(key=lambda r: (not r["tagged"], r["page"] or 0, r["clause"] or ""))
        offered, chars = 0, 0
        if mine:
            for r in mine:
                t = str(r["source_text"] or r["requirement_text"] or "")
                cut = len(t) > RULE_CHARS
                t = t[:RULE_CHARS] + (
                    " [CUT: rule text longer than shown]" if cut else ""
                )
                if chars + len(t) > BOOK_BUDGET or used + len(t) > MATERIAL_BUDGET:
                    break
                n += 1
                rows.append(
                    {
                        "rule": f"R{n:04d}",
                        "book": b["alias"],
                        "book_id": b["book"],
                        "clause": str(r["clause"] or ""),
                        "page": int(r["page"] or 0),
                        "text": t,
                        "req_id": r["id"],
                    }
                )
                offered, chars, used = offered + 1, chars + len(t), used + len(t)
            stats.append(
                {
                    "alias": b["alias"],
                    "identifier": b["identifier"],
                    "rules_offered": offered,
                    "rules_total": len(mine),
                    "cut": offered < len(mine),
                }
            )
        else:
            pages = text.pages(b["book"])
            shown = 0
            for p, t in sorted(pages.items()):
                if chars + len(t) > TEXT_BOOK_BUDGET or used + len(t) > MATERIAL_BUDGET:
                    break
                rows.append(
                    {
                        "page_of": b["alias"],
                        "book_id": b["book"],
                        "page": p,
                        "page_text": t,
                    }
                )
                shown, chars, used = shown + 1, chars + len(t), used + len(t)
            stats.append(
                {
                    "alias": b["alias"],
                    "identifier": b["identifier"],
                    "pages_offered": shown,
                    "pages_total": len(pages),
                    "cut": shown < len(pages),
                }
            )
    return rows, stats


def _material_line(r: dict) -> str:
    if "rule" in r:
        return _dumps(
            {
                "rule": r["rule"],
                "book": r["book"],
                "clause": r["clause"],
                "page": r["page"],
                "text": r["text"],
            }
        )
    return _dumps(
        {"book": r["page_of"], "page": r["page"], "page_text": r["page_text"]}
    )


def _batches(rows: list[dict]) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for r in rows:
        ln = len(_material_line(r))
        if cur and size + ln > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += ln
    if cur:
        out.append(cur)
    return out or [[]]
