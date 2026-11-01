"""#1473: why a page has no reading, in plain words, and the CRS note that names it.

A page stays NOT READ; this only says why. One of three kinds the owner accepts
(blank page, image with no reading, excluded from the index on purpose, with
its rule), else the recorded reason: a page with content that simply failed is
never given a kind that excuses it."""

from __future__ import annotations

from .crs_blank_fields import page_list

BLANK_PAGE = "blank page"
IMAGE_NO_READING = "image with no reading"
NOTE_PAGE_NOT_READ = "Page not read - no reading came back"


def unread_page_words(row: dict) -> str:
    reason = str(row["index_reason"] or "")
    if row["index_status"] == "excluded" and reason.startswith("page_classified_"):
        return f"excluded from the index on purpose (rule {reason.split(',')[0]})"
    if row["native_status"] == "empty":
        return BLANK_PAGE
    if row["native_status"] == "needs_ocr" or row["ocr_status"] in (
        "pending",
        "failed",
    ):
        return IMAGE_NO_READING
    return str(row["facts_reason"] or "no reading came back for this page")


def notes(outcome: dict | None) -> list[dict]:
    """One CRS note naming the unread pages and each reason. Only a run stored
    with PAGE_READ_BY_READING_ENABLED carries `pages_not_read_why`."""
    why = ((outcome or {}).get("page_coverage") or {}).get("pages_not_read_why") or {}
    if not why:
        return []
    order = sorted(why, key=int)
    plural = len(order) != 1
    detail = (
        f"Page{'s' if plural else ''} {page_list([int(p) for p in order])} "
        f"{'were' if plural else 'was'} not read: "
        + "; ".join(f"page {p}: {why[p]}" for p in order)
        + "."
    )
    return [
        {
            "note": NOTE_PAGE_NOT_READ,
            "standard": "",
            "count": len(order),
            "detail": detail,
        }
    ]
