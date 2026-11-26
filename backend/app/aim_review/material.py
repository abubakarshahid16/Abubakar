"""The clause material of the checklist build (S3 and the attack): each chosen book's rules, tagged for the equipment first then
by page, or the pages of a book that holds no stored rules; budgeted, every cut counted; and the batches S3 reads them in."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from . import library as L
from .budget import cap

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
    # the SAME material on every model (26 Nov 2026: the local run's smaller book and total sizes cut its checklist to a tenth of
    # the rules, 31 items against 93 on the valve copy): a local run reads it in more, smaller calls (`_batches`), never less of it
    rule_chars, book_budget = RULE_CHARS, BOOK_BUDGET
    text_book_budget, material_budget = TEXT_BOOK_BUDGET, MATERIAL_BUDGET
    for b in sel["books"]:
        mine = pool_by_book.get(b["book"], [])
        if b["chosen_subjects"] != "all":
            mine = [r for r in mine if r["subject"] in b["chosen_subjects"]]
        mine.sort(key=lambda r: (not r["tagged"], r["page"] or 0, r["clause"] or ""))
        offered, chars = 0, 0
        if mine:
            for r in mine:
                t = str(r["source_text"] or r["requirement_text"] or "")
                cut = len(t) > rule_chars
                t = t[:rule_chars] + (
                    " [CUT: rule text longer than shown]" if cut else ""
                )
                if chars + len(t) > book_budget or used + len(t) > material_budget:
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
                if chars + len(t) > text_book_budget or used + len(t) > material_budget:
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
    """The calls the rule material is read in: whole rows up to the batch size. On the local model whole GROUPS (`_groups`: a
    book's rules of one clause group, or all the pages of a book with no stored rules), so no clause group and no clause
    running over a page break is ever split across two calls; one clause larger than the size goes whole in a call of its own."""
    from .budget import is_local

    batch_chars = cap(BATCH_CHARS, "batch_chars")
    units = _groups(rows, batch_chars) if is_local() else [[r] for r in rows]
    out, cur, size = [], [], 0
    for unit in units:
        ln = sum(len(_material_line(r)) for r in unit)
        if cur and size + ln > batch_chars:
            out.append(cur)
            cur, size = [], 0
        cur += unit
        size += ln
    if cur:
        out.append(cur)
    return out or [[]]


def _groups(rows: list[dict], most: int | None = None) -> list[list[dict]]:
    """The rows by book, then by the top level of their clause number ("6.2.1" -> "6"), in the order they first appear; the
    pages of a book with no stored rules are one group (owner via the planner, 26 Nov 2026 05:20: one whole book or clause
    group per call, never a clause split). A group larger than `most` characters is taken by its next clause level instead
    ("6.2", "6.3", ...), down to one clause number, which then goes whole: a call stays near the size, no clause is split."""
    out: list[list[dict]] = []
    for group in _by_clause(rows, 1).values():
        out += _deeper(group, 1, most)
    return out


def _clause_key(r: dict, level: int) -> tuple:
    if "rule" not in r:
        return ("pages", r.get("book_id"))
    parts = [p.strip() for p in str(r.get("clause") or "").split(".") if p.strip()]
    return ("rules", r.get("book_id"), tuple(parts[:level]) or ("-",))


def _by_clause(rows: list[dict], level: int) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(_clause_key(r, level), []).append(r)
    return groups


#: A page that BEGINS with a numbered clause heading ("6.2 Title"): the page break before it ends a clause.
_CLAUSE_START = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+\S")


def _pages(group: list[dict], most: int | None) -> list[list[dict]]:
    """A no-rule book's pages: whole; over `most` characters, split only before a page that begins with a clause heading,
    so no clause runs over a split (a run with no such page stays whole)."""
    runs, cur, size = [], [], 0
    for r in group:
        ln = len(_material_line(r))
        if (
            cur
            and most is not None
            and size + ln > most
            and _CLAUSE_START.match(str(r.get("page_text") or ""))
        ):
            runs.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += ln
    return [*runs, cur] if cur else runs


def _deeper(group: list[dict], level: int, most: int | None) -> list[list[dict]]:
    if group and "rule" not in group[0]:
        return _pages(group, most)
    size = sum(len(_material_line(r)) for r in group)
    finer = _by_clause(group, level + 1)
    if most is None or size <= most or len(finer) < 2:
        return [group]  # within the size, one clause number, or pages: whole
    return [g for sub in finer.values() for g in _deeper(sub, level + 1, most)]


def halves(batch: list[dict]) -> tuple[list[dict], list[dict]]:
    """A cut answer's batch asked again in two halves: on the local model at a group boundary when it holds two or more groups
    (a group is never split there), else by whole rows; on Claude by rows, as before."""
    from .budget import is_local

    groups = _groups(batch) if is_local() else []
    if len(groups) >= 2:
        h = len(groups) // 2
        return [r for g in groups[:h] for r in g], [r for g in groups[h:] for r in g]
    h = len(batch) // 2
    return batch[:h], batch[h:]
