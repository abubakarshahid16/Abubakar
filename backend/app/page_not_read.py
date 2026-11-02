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
NOTE_FILE_PARTLY_READ = "File not fully read"


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
    """The CRS notes naming the unread pages and each reason (only a run stored
    with PAGE_READ_BY_READING_ENABLED carries `pages_not_read_why`), then one
    note for pages read in part, then what intake left out (only a document
    read with ONE_INTAKE_ENABLED carries `intake_reasons`)."""
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
    out.extend(_intake_note((outcome or {}).get("page_coverage") or {}))
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


# #1550: ONE meaning of "not read" with PAGE_READ_BY_READING_ENABLED - no reading
# came back for the page, the count the CRS footer and the issue gate use. A read
# page no datasheet field was taken from is said as that, never "not read".
NOTE_NO_FIELD_PAGES = "No datasheet field taken from some pages - engineer to check"


def by_reading(page_coverage: dict | None) -> bool:
    """Was this page coverage stored with PAGE_READ_BY_READING_ENABLED?"""
    return "pages_not_read" in (page_coverage or {})


def _split(cov: dict | None, pages: list) -> tuple[list, list]:
    """`pages` as (no reading came back, read with no field taken): an unread page
    is never also counted as no field taken."""
    not_read = set((cov or {}).get("pages_not_read") or [])
    return [p for p in pages if p in not_read], [p for p in pages if p not in not_read]


def unread_clause(cov: dict | None, unread: list) -> str:
    """How a finding's rationale says the fields list. Off: "pages 1-3 were not
    read into fields", as before. On: "not read" only for `pages_not_read`."""
    plural = "s" if len(unread) != 1 else ""
    if not by_reading(cov):
        return f"page{plural} {page_list(unread)} were not read into fields"
    return _on_clause(cov, unread)


def _on_clause(cov: dict | None, unread: list) -> str:
    not_read, no_field = _split(cov, unread)
    parts = []
    if not_read:
        word = "pages" if len(not_read) != 1 else "page"
        verb = "were" if len(not_read) != 1 else "was"
        parts.append(f"{word} {page_list(not_read)} {verb} not read")
    if no_field:
        one = len(no_field) == 1
        parts.append(
            f"page{'' if one else 's'} {page_list(no_field)} had no datasheet field "
            f"taken from {'it' if one else 'them'}"
        )
    return "; ".join(parts) or "some pages had no datasheet field taken from them"


def field_note(outcome: dict | None, unread: list, pages: list | None) -> dict | None:
    """The Review note for the `unread` findings (no value, on a page with no
    reading or no field taken) of a run stored with the switch on; None with it
    off, where `crs_mapping` keeps its own note."""
    cov = (outcome or {}).get("page_coverage")
    if not by_reading(cov):
        return None
    pages = pages or []
    n = len(unread)
    only_unread = bool(pages) and not _split(cov, pages)[1]
    return {
        "note": NOTE_PAGE_NOT_READ if only_unread else NOTE_NO_FIELD_PAGES,
        "standard": "",
        "count": n,
        "detail": f"{n} requirement{'s' if n != 1 else ''} could not be checked on this "
        f"submittal: {_on_clause(cov, pages)}. The values may be there.",
    }


def stored_reasons(cov: dict) -> dict:
    """The run's stored `not_read_reasons`, for showing. Switch off: as stored. On:
    a page that WAS read is not said to be "not counted as read"; the stored run
    is not rewritten (`howData.incompletePageReasons` says the same)."""
    stored = cov.get("not_read_reasons") or {}
    if not by_reading(cov):
        return stored
    not_read = {str(p) for p in cov.get("pages_not_read") or []}
    return {k: v if k in not_read else _read_page_words(v) for k, v in stored.items()}


def _read_page_words(reason):
    if not isinstance(reason, str):
        return reason
    return reason.replace(
        "so it is not counted as read", "so no datasheet field was taken from it"
    ).replace("not counted as the page read into fields", "no datasheet field taken")


def unchecked_page_parts(cov: dict) -> list[tuple[str, str]]:
    """The page parts of `absence.unchecked_parts`, as (part, line). Switch off:
    the fields list, "not read into fields", as before."""
    fields = cov.get("pages_not_read_into_fields") or []
    could_not = "values on them could not be checked."
    if not by_reading(cov):
        line = f"{len(fields)} page(s) of this submittal were not read into fields"
        return [("unread_pages", f"{line}; {could_not}")] if fields else []
    not_read = cov.get("pages_not_read") or []
    no_field = [p for p in fields if p not in set(not_read)]
    out = []
    if not_read:
        line = f"{len(not_read)} page(s) of this submittal were not read; {could_not}"
        out.append(("unread_pages", line))
    if no_field:
        line = (
            f"{len(no_field)} page(s) of this submittal were read, but no datasheet "
            f"field was taken from them; {could_not}"
        )
        clean = cov.get("pages_read_no_field") or []
        if clean:  # a different fact: both readers looked; not held for the engineer
            line += (
                f" {len(clean)} other page(s) were read by both readers and held no "
                "checklist field; they are not in this count."
            )
        out.append(("no_field_pages", line))
    return out


def incomplete_words(cov: dict | None, reading: dict) -> str:
    """The incomplete `reading`'s pages (`incomplete_pages`) in words. The
    approval hold is unchanged; only the words follow the switch. Off: "pages
    1-3 not read in full", as before. On: "not read" only for `pages_not_read`,
    "no datasheet field taken from" for the rest of the fields list, and "not
    read in full" for any other page (an AI reader that did not finish it)."""
    pages = reading.get("incomplete_pages") or []
    if not by_reading(cov):
        plural = "s" if len(pages) != 1 else ""
        return f"page{plural} {page_list(pages)} not read in full"
    not_read = set((cov or {}).get("pages_not_read") or [])
    fields = set((cov or {}).get("pages_not_read_into_fields") or [])
    groups = (
        ([p for p in pages if p in not_read], "not read"),
        ([p for p in pages if p in fields - not_read], "no datasheet field taken"),
        ([p for p in pages if p not in fields | not_read], "not read in full"),
    )
    return "; ".join(
        f"page{'s' if len(ps) != 1 else ''} {page_list(ps)} {words}"
        for ps, words in groups
        if ps
    )


def tier_pages(cov: dict) -> dict:
    """`review_tiers.RunFacts`' page sets (tiers.ts `pageFactsOf`). Switch off:
    the fields list is "page not read", as before; on: `pages_not_read`, and the
    rest of the fields list is `pages_no_field` ("no field taken")."""
    fields = cov.get("pages_not_read_into_fields") or []
    if not by_reading(cov):
        return {"pages_not_read": frozenset(fields)}
    not_read = frozenset(cov.get("pages_not_read") or [])
    return {"pages_not_read": not_read, "pages_no_field": frozenset(fields) - not_read}


def readiness_part(cov: dict, into_fields: int, current: bool) -> dict:
    """The readiness strip's page numbers (`page_ledger.readiness_pages`): pages
    read, unread pages and why. Switch off: pages read into fields, as before.
    `current` False: the ledger may not be counted on - no number (null, never 0)."""
    read = cov.get("pages_read")
    count = len(read) if read is not None else into_fields
    unread = cov.get("pages_not_read", cov.get("pages_not_read_into_fields"))
    why = cov.get("pages_not_read_why", cov.get("not_read_reasons"))
    return {
        "pages_read": count if current else None,
        "unread_pages": unread or [],
        "unread_page_reasons": why or {},
    }
