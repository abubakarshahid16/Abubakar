"""The reading record of a run: what the readers read, what the AI page reader did not do, and THE run's unread pages (moved
unchanged out of `page_ledger`, which keeps the per-page ledger; K3 adds the marker for a step skipped on purpose and the thin-page
measure). `page_ledger` re-exports every name, so callers do not change. Pure: reads the record it is given, never a database.

A page the AI page reader was NEVER RUN on (the bar, on purpose) is read from its own text, not unread; it is "not fully read" only
when that text is thin by the app's own measure or the code readers found no field on it. A failure, a page no reader read and a
missing record keep their words. The writer marks the pages `skipped_on_purpose`; a record stored before the marker is told apart
by the bar's own words (`local_engine_bar.is_bar_note`), in this one place."""

from __future__ import annotations

from . import local_engine_bar, page_not_read

READING_COMPLETE = "complete"
READING_INCOMPLETE = "incomplete"
LITTLE_TEXT = "little text on this page and the AI page reader did not run"
NOT_RUN_WORDS = "The AI page reader did not run on {n} page{s} in this review ({why}); {they} read from their own text."


def _ai_pages(reader: dict, total: int, pages: dict) -> tuple[dict, dict]:
    """(pages the AI reader failed on or left thin, pages it was never run on), each page -> why, in words.

    A page the reader was NEVER RUN on (the bar, on purpose; the writer marks it `skipped_on_purpose`, and a record stored before
    the marker is told apart by the bar's own words, `local_engine_bar.is_bar_note`, in this one place) is read from its own text:
    it is not unread. It counts as not fully read only when that text is thin by a stated measure (`pages_thin`: under
    `OCR_MIN_USABLE_CHARS`, the app's own minimum for a usable text layer) or the code readers found no field on it.
    A scan stays unread by the ledger. A page the reader tried and failed on is a failure, whatever else was skipped."""
    engine = reader.get("engine") or "AI"
    failed: dict[int, str] = {}
    for page in reader.get("timed_out") or []:
        failed[int(page)] = f"the {engine} reader timed out on this page"
    raw: dict[int, object] = {}
    code_only = reader.get("code_only")
    for page, why in code_only.items() if isinstance(code_only, dict) else ():
        raw[int(page)] = why
    for page in reader.get("cut_off") or []:
        failed.setdefault(
            int(page), f"the {engine} reader was cut off before this page"
        )
    for page, why in (reader.get("partly_read") or {}).items():
        failed.setdefault(
            int(page), f"the {engine} reader read this page in part ({why})"
        )
    for key, word in (("unavailable", "unavailable"), ("stopped", "stopped")):
        if reader.get(key) and (
            key == "unavailable" or int(reader.get("pages_read") or 0) < total
        ):
            for page in range(1, total + 1):
                raw.setdefault(page, reader[key])
                if key == "stopped" or not local_engine_bar.is_bar_note(reader[key]):
                    failed.setdefault(
                        page, f"the {engine} reader was {word} ({reader[key]})"
                    )
    marked = {int(p) for p in reader.get("skipped_on_purpose") or []}
    skipped = {
        p: f"the {engine} reader was not run on this page ({why})"
        for p, why in sorted(raw.items())
        if (p in marked or local_engine_bar.is_bar_note(why)) and p not in failed
    }
    for page, why in raw.items():
        if page not in skipped and page not in failed:
            failed[page] = f"the {engine} reader did not read this page ({why})"
    thin = {int(p) for p in pages.get("pages_thin") or []} | {
        int(p) for p in pages.get("pages_read_no_field") or []
    }
    for page in [p for p in skipped if p in thin]:
        failed[page] = LITTLE_TEXT
        del skipped[page]
    keep = {p: w for p, w in failed.items() if 1 <= p <= total}
    return dict(sorted(keep.items())), {
        p: w for p, w in skipped.items() if 1 <= p <= total
    }


def skipped_line(skipped: dict) -> str:
    """The pages line, once, in plain words: how many pages the AI page reader did not run on, and why (the reasons are the
    writer's own; one reason is named, a second distinct one says 'other reasons')."""
    n = len(skipped)
    whys = {w.rsplit("(", 1)[-1].rstrip(")") for w in skipped.values()}
    why = next(iter(whys)) if len(whys) == 1 else "different reasons"
    return NOT_RUN_WORDS.format(
        n=n, s="" if n == 1 else "s", why=why, they="it was" if n == 1 else "they were"
    )


def reading_gaps(reader: dict | None, pages: dict) -> dict:
    """What the AI reader did not read, and the run's reading status.

    `reader` is `datasheets.latest_reader_summary`; `pages` is `coverage()`.
    Returns the keys to merge into the run's stored page coverage:
      pages_ai_not_read    pages the configured AI reader did not read
      ai_not_read_reasons  {page: why}, in words
      reading              {"status", "pages_total", "incomplete_pages", "reasons"}
    With NO reader recorded (it was off, or the sheet was read before
    summaries were kept) nothing is claimed about the AI: the status is only
    about the pages the code readers did not read."""
    total = pages.get("pages_total")
    unread = [int(p) for p in pages.get("pages_not_read_into_fields") or []]
    ai_missing: dict[int, str] = {}
    skipped: dict[int, str] = {}
    if reader and total:
        ai_missing, skipped = _ai_pages(reader, int(total), pages)
    # #918: a page a CODE reader failed on, or something the office reader left
    # out, makes the reading incomplete whatever the AI did.
    failed: dict[int, str] = {}
    for page, readers in ((reader or {}).get("page_failures") or {}).items():
        failed[int(page)] = "a reader failed on this page (" + ", ".join(sorted(readers)) + ")"
    notes = list((reader or {}).get("reading_notes") or [])
    incomplete = sorted(set(unread) | set(ai_missing) | set(failed))
    return {
        "pages_ai_not_read": sorted(ai_missing),
        "ai_not_read_reasons": {str(p): why for p, why in ai_missing.items()},
        # only when something was skipped on purpose: the shape without it is unchanged
        **(
            {
                "pages_ai_skipped": sorted(skipped),
                "ai_skipped_reasons": {str(p): w for p, w in skipped.items()},
                "ai_skipped_line": skipped_line(skipped),
            }
            if skipped
            else {}
        ),
        "reading": {
            "status": READING_INCOMPLETE if incomplete or notes or not total else READING_COMPLETE,
            "pages_total": total,
            "incomplete_pages": incomplete,
            "reasons": ({"no page of this submittal is accounted for": True} if not total else {}),
            # only when there is something: the shape without it is unchanged
            **({"failed_pages": {str(p): why for p, why in sorted(failed.items())}} if failed else {}),
            **({"notes": notes} if notes else {}),
        },
    }


def run_reader(outcome: dict | None) -> dict | None:
    """The AI reader's record a run stored (`requirement_split.reader`), or
    None when the run stored none."""
    split = (outcome or {}).get("requirement_split")
    reader = split.get("reader") if isinstance(split, dict) else None
    return reader if isinstance(reader, dict) else None


def run_unread_pages(
    page_coverage: dict | None, reader: dict | None = None
) -> list[int]:
    """Order 127: THE run's unread pages, one definition for the issue gate, the
    run summary and the runs list. Union of `pages_not_read_into_fields`,
    `pages_ai_not_read` and (runs stored before PF3 kept `pages_ai_not_read`)
    the AI reader's own `timed_out` pages. Only those legacy time-out pages are
    limited to 1..pages_total: `pages_total` counts ledger rows, not the highest
    page number, and the gate must never drop a page it asked for before.
    Sorted, no duplicates. Pure: reads nothing."""
    cov = page_coverage if isinstance(page_coverage, dict) else {}
    # #1473: a run stored with the page-read switch on names the pages no
    # reading came back for (`pages_not_read`); older runs, the fields rule.
    unread = cov.get("pages_not_read", cov.get("pages_not_read_into_fields"))
    pages = {int(p) for p in unread or []}
    # a page the AI reader was never run on (barred on purpose) is not unread: runs stored before `pages_ai_skipped` carry it in
    # `pages_ai_not_read` with the skip's own reason (K3), so it is told apart by that reason
    ai_reasons = cov.get("ai_not_read_reasons") or {}
    pages |= {
        int(p)
        for p in cov.get("pages_ai_not_read") or []
        if int(p) in pages or not local_engine_bar.is_bar_note(ai_reasons.get(str(p)))
    }
    if isinstance(reader, dict):
        timed_out = {int(p) for p in reader.get("timed_out") or []}
        total = cov.get("pages_total")
        if total is not None:
            timed_out = {p for p in timed_out if 1 <= p <= int(total)}
        pages |= timed_out
    return sorted(pages)


def run_unread_reasons(
    page_coverage: dict | None, reader: dict | None = None
) -> dict[str, str]:
    """Why each of those pages was not read, keyed by the page as a string:
    `not_read_reasons` wins over `ai_not_read_reasons` (the gate's order since
    PF5), and a legacy time-out page with neither gets "the AI reader timed out
    on this page". A page with no recorded reason is absent."""
    cov = page_coverage if isinstance(page_coverage, dict) else {}
    recorded = {
        **{str(k): v for k, v in (cov.get("ai_not_read_reasons") or {}).items()},
        **{str(k): v for k, v in page_not_read.stored_reasons(cov).items()},
        # #1473: the plain-words reason, stored when the page-read switch was on.
        **{str(k): v for k, v in (cov.get("pages_not_read_why") or {}).items()},
    }
    timed_out = (
        {int(p) for p in reader.get("timed_out") or []}
        if isinstance(reader, dict)
        else set()
    )
    reasons: dict[str, str] = {}
    for page in run_unread_pages(cov, reader):
        why = recorded.get(str(page))
        if not why and page in timed_out:
            why = "the AI reader timed out on this page"
        if why:
            reasons[str(page)] = why
    return reasons


def skipped_pages(reasons: dict) -> list[int]:
    """The pages whose recorded reason is the bar's: the structured marker the reader summary writes (`skipped_on_purpose`)."""
    return sorted(p for p, why in reasons.items() if local_engine_bar.is_bar_note(why))

