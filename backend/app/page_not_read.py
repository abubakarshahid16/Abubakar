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


NOTE_FILE_PARTLY_READ = "File not fully read"


def _intake_note(coverage: dict) -> list[dict]:
    """ONE_INTAKE_ENABLED: what intake left out of a workbook (a cut sheet, a
    hidden sheet, a formula with no stored result), each with its reason."""
    found = coverage.get("intake_reasons") or {}
    if not found:
        return []
    parts = [
        ("the file" if p == "0" else f"page {p}") + ": " + "; ".join(found[p])
        for p in sorted(found, key=int)
    ]
    return [
        {
            "note": NOTE_FILE_PARTLY_READ,
            "standard": "",
            "count": len(found),
            "detail": "Not read or only partly read - " + " | ".join(parts) + ".",
        }
    ]


def notes(outcome: dict | None) -> list[dict]:
    """CRS notes naming the unread pages and each reason. Only a run stored
    with PAGE_READ_BY_READING_ENABLED carries `pages_not_read_why`; only a
    document read with ONE_INTAKE_ENABLED carries `intake_reasons`."""
    coverage = (outcome or {}).get("page_coverage") or {}
    out = _intake_note(coverage)
    why = coverage.get("pages_not_read_why") or {}
    if not why:
        return out
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
        },
        *out,
    ]
