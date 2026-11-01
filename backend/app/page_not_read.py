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


DROPPED_WITH_CONTENT = "set aside by a rule although it holds clause text - not excused"


def unread_page_words(row: dict, *, dropped_content: bool = False) -> str:
    """`dropped_content`: the chunker flagged this page's exclusion as real body
    text (exclusions.clause_headings), so the rule is not an excuse."""
    reason = str(row["index_reason"] or "")
    if row["index_status"] == "excluded" and reason.startswith("page_classified_"):
        if dropped_content:
            return f"{DROPPED_WITH_CONTENT} (rule {reason.split(',')[0]})"
        return f"excluded from the index on purpose (rule {reason.split(',')[0]})"
    # A failed or pending reading first: a scan whose OCR failed has an empty
    # text layer too, and is not a blank page (review of #1519).
    if row["native_status"] == "needs_ocr" or row["ocr_status"] in (
        "pending",
        "failed",
    ):
        return IMAGE_NO_READING
    if row["native_status"] == "empty":
        return BLANK_PAGE
    return str(row["facts_reason"] or "no reading came back for this page")


NOTE_PAGE_READ_IN_PART = "Page read in part - some cells or rows were left out"
_PART_MARK = "column rows:"


def partly_read(outcome: dict | None) -> dict[str, str]:
    """{page: what was left out} for pages the column-row reading (#1478) left
    cells or rows out of; from the run's reading gaps (`failed_pages`)."""
    cov = (outcome or {}).get("page_coverage") or {}
    failed = (cov.get("reading") or {}).get("failed_pages") or {}
    unread = {str(p) for p in cov.get("pages_not_read_why") or {}}
    return {
        str(p): w[w.index(_PART_MARK) :].rstrip(") ")
        for p, w in failed.items()
        if _PART_MARK in str(w) and str(p) not in unread
    }


def notes(outcome: dict | None) -> list[dict]:
    """The CRS notes naming the unread pages and each reason (only a run stored
    with PAGE_READ_BY_READING_ENABLED carries `pages_not_read_why`), then one
    note for pages read in part."""
    out = _unread_note(outcome)
    part = partly_read(outcome)
    if part:
        order = sorted(part, key=int)
        out.append(
            {
                "note": NOTE_PAGE_READ_IN_PART,
                "standard": "",
                "count": len(order),
                "detail": "; ".join(f"page {p}: {part[p]}" for p in order) + ".",
            }
        )
    return out


def _unread_note(outcome: dict | None) -> list[dict]:
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
