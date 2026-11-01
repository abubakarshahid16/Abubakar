"""The reader-coverage line of a datasheet review (moved out of datasheet_checks.py, #1472)."""

from __future__ import annotations


def coverage(results: list[dict]) -> dict | None:
    """The reader-coverage line of a review (planner 2026-10-10, roadmap R11):
    of the checklist's fields (each field once, across tags), how many were
    READ as a fact, and how many are on the sheet but were NOT read (a reader
    gap, with the pages): the to-do list for the datasheet reader. None when
    the review ran no checklist."""
    # A calculation compares a field the `required` items already count; it
    # is not a field of its own (R13), so the reader-coverage line is unchanged.
    items = [r for r in results if r.get("checklist") and not r.get("calc")]
    if not items:
        return None
    fields: dict[str, str] = {}
    gap_pages: dict[str, set] = {}
    for r in items:
        role = r.get("role") or ""
        state = (
            "read" if r.get("fact_id") else ("gap" if r.get("reader_gap") else "absent")
        )
        # a field read for one tag counts as read; a gap only if never read
        if fields.get(role) != "read":
            fields[role] = (
                "read"
                if state == "read"
                else (fields.get(role) if fields.get(role) == "gap" else state)
            )
        if r.get("reader_gap"):
            gap_pages.setdefault(role, set()).update(r.get("pages") or [])
    gaps = sorted(f for f, st in fields.items() if st == "gap")
    return {
        "fields": len(fields),
        "read": sum(1 for st in fields.values() if st == "read"),
        "on_sheet_not_read": len(gaps),
        "gap_pages": sorted({p for f in gaps for p in gap_pages.get(f, ())}),
    }
