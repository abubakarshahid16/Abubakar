"""Order 161 D: a SERIES OF ITEMS is one CRS row listing the items.

"N1 Size" ... "N8 Size" were eight rows with the same clause and the same
outcome, differing only in the item's mark. `merge` finds such series and
gives their findings the label without the index; the ordinary one-row-per-
field grouping in `crs_mapping` then does the rest, and `marks` / `marks_text`
name the items on the row.

GENERAL, NOT PER LAYOUT: nothing here knows a table shape or a label spelling.
A series needs two or more different numbers with the same letters ("H2
content" and "O2 content" are two quantities, not a series), the same bucket,
the same datasheet page and the whole same set of clauses behind each item.
Rejected findings never make or extend a series (rejecting one comment must
not renumber the row beside it).
"""

from __future__ import annotations

import re

#: A label token that is an item INDEX: one to three letters then up to three
#: digits ("N3", "M12"). A bare number is a rating or a size, never an index
#: ("Class 150" and "Class 300" are two ratings, not two items).
INDEX_TOKEN = re.compile(r"^([A-Za-z]{1,3})(\d{1,3})$")
#: A series row names at most this many items, then "and k more".
MAX_ITEM_MARKS = 12


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _clause_identity(f: dict) -> tuple:
    return (
        str(f.get("standard_document_id") or ""),
        str(f.get("standard_clause") or ""),
        _fold(f.get("requirement_source_text")),
    )


def merge(findings: list[dict]) -> None:
    """In place and idempotent. Findings whose field labels differ ONLY in one
    index token, and that share bucket, page and clause set, get the label
    without the index (`crs_field_label`: "Size") and keep their own mark in
    `crs_item_mark` ("N1") and their own label in `crs_item_label` ("N1 Size"),
    which keeps their per-finding number key (`crs_mapping._subject_key`) the
    one earlier runs stored."""
    from . import crs_mapping as cm  # crs_mapping imports this module

    cohorts: dict[tuple, dict[tuple, dict]] = {}
    for f in findings:
        # An engineer's own comment is never re-labelled under their feet.
        if cm._rejected(f) or cm._confirmed(f) or f.get("crs_item_mark"):
            continue
        bucket = cm._bucket_of(f)
        if bucket not in cm.FIELD_GROUPED_BUCKETS:
            continue
        tokens = cm._field_label(f).split()
        for i, token in enumerate(tokens):
            m = INDEX_TOKEN.match(token)
            if not m:
                continue
            masked = (*map(_fold, tokens[:i]), "#", *map(_fold, tokens[i + 1 :]))
            key = (bucket, f.get("contractor_page"), i, masked)
            variant = cohorts.setdefault(key, {}).setdefault(
                (m.group(1).lower(), int(m.group(2))),
                {"clauses": set(), "members": []},
            )
            variant["clauses"].add(_clause_identity(f))
            variant["members"].append((f, tokens, i, token))
    claimed: set[int] = set()
    for key in sorted(cohorts, key=lambda k: (k[2], str(k[3]))):
        variants = cohorts[key]
        letters = {v[0] for v in variants}
        clause_sets = {frozenset(v["clauses"]) for v in variants.values()}
        if len(variants) < 2 or len(letters) != 1 or len(clause_sets) != 1:
            continue
        members = [m for v in variants.values() for m in v["members"]]
        if any(id(f) in claimed for f, _t, _i, _tok in members):
            continue
        for f, tokens, i, token in members:
            claimed.add(id(f))
            f["crs_item_label"] = " ".join(tokens)
            f["crs_field_label"] = " ".join(tokens[:i] + tokens[i + 1 :])
            f["crs_item_mark"] = token


def mark_order(mark: str | None) -> tuple:
    """Series order: by letters, then number; a finding with no mark last."""
    m = INDEX_TOKEN.match(mark or "")
    return (0, m.group(1).lower(), int(m.group(2))) if m else (1, "", 0)


def marks(group: list[dict]) -> list[str]:
    """The item marks a series row stands for, in numeric order."""
    seen = {g["crs_item_mark"] for g in group if g.get("crs_item_mark")}
    return sorted(seen, key=mark_order)


def in_series_order(finding: dict) -> tuple:
    """Sort key putting a row's findings in the series' own order."""
    return mark_order(finding.get("crs_item_mark"))


def items_suffix(group: list[dict]) -> str:
    """ ", items N1, N2, ... and k more" after a field's name, or "" when the
    row is not a series."""
    found = marks(group)
    if len(found) > MAX_ITEM_MARKS:
        found = [*found[:MAX_ITEM_MARKS], f"and {len(found) - MAX_ITEM_MARKS} more"]
    return f", items {', '.join(found)}" if found else ""


def own_label(finding: dict) -> str | None:
    """The finding's field label as the datasheet printed it ("N1 Size"), kept
    for its per-finding number key even after the series gave it a shared one."""
    return finding.get("crs_item_label") or finding.get("crs_field_label")


def item_name(finding: dict) -> str:
    """Who a value belongs to in a row that lists several: the equipment tag
    and the item's mark ("V-100 N1"), else "untagged"."""
    parts = [finding.get("equipment_tag"), finding.get("crs_item_mark")]
    return " ".join(str(p) for p in parts if p) or "untagged"
