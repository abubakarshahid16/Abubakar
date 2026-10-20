"""The page ledger (master order B3): every page accounted for, with a reason.

WHY IT EXISTS. Page state was spread over `pages`, `page_ocr`, `chunks` and
`exclusions`, and the one per-page outcome that decides what a review may say
about a contractor submittal - were fields read from this page, and if not, why
- was computed by `datasheets.extract_facts` and thrown away. A review then
wrote "the submittal states no value for this requirement" when the value
could sit on a page nobody had read into fields. NORTH-STAR 2.2: "Not
retrieved" never means "not present"; a `MISSING_INFORMATION` finding must
preserve the exact contractor pages searched.

WHAT IT IS NOT. Not a second source of truth: every column except `facts_*` is
recomputed from the stage tables by `refresh`, and `facts_*` falls back to a
derivation from the stored facts - labelled `derived`, with the reason stated
as not recorded - when extraction has not written it. Deleting the table loses
nothing that `refresh` and a re-extraction cannot rebuild.

Ids, statuses, counts and rule names only. Never page text.
"""
from __future__ import annotations

from datetime import UTC, datetime

from . import errors
from .config import settings
from .db import connect

SUBMITTAL_ROLE = "CONTRACTOR_SUBMITTAL"

#: Fact statuses that mean "no field was read from this page". A page in one
#: of these states was NOT searched for values, so a review may not say the
#: contractor omitted a value it could hold.
NOT_READ_INTO_FIELDS = frozenset({"no_facts", "unreadable", "not_reached", "not_run"})
#: Order 165 (item E): a page the code readers gave no fact AND the AI reader
#: read without error and put nothing forward on (no accepted reading, no
#: refused proposal, no part left unread). It is READ - two readers looked and
#: found no datasheet field on it (a cover, a hold list, a contents page) - so
#: it is not in `NOT_READ_INTO_FIELDS`; it is not a page fields were read from
#: either (`fact_pages`), and `coverage` lists it apart.
READ_NO_FIELD = "no_fields"
#: The rule/text readers' extraction methods. A page whose current facts all
#: came from any OTHER reader (geometry, vision, model) is read - the ledger
#: says "facts" - but an ABSENCE there is not the contractor's omission: the
#: page reader is not known to read every field on a page, so a value it did
#: not find may still be printed there (owner decision 2026-09-26; honesty
#: audit entry 68). An allow-list, so a new reader defaults to the cautious side.
#: 'xlsx' / 'docx' (DATASHEET_OFFICE_INPUT): the same rules reader, over every
#: row of a rendered sheet or Word document.
TEXT_READER_METHODS = frozenset({"extracted", "ocr_fallback", "grid", "xlsx", "docx"})

#: THE FALLBACK ONLY - used when this page's real vision routing decision
#: was never recorded (`vision_recorded_by IS NULL`): the geometry/vision
#: reader is off, or this document has not been (re-)extracted since the
#: 2026-09-27 fix that started recording it. Before that fix `refresh`
#: printed this SAME text for every page of every document regardless of
#: what actually happened - the vision reader (B7, `datasheets.vision_route`)
#: has existed since before this constant's name was written, and no page
#: had ever recorded a REAL routing decision here (honesty audit).
VISION_NOT_RECORDED_OFF = "the geometry/vision reader is off (settings.geometry_reader_enabled)"
VISION_NOT_RECORDED_STALE = ("vision routing has not been recorded for this page yet; "
                             "re-run extraction (\"Read unread pages\") to record it")


#: Said for a `no_fields` page the coverage does NOT count as read: no page of
#: the sheet gave a single field, so "two readers found none" proves nothing
#: (a wrong document, a text layer that is noise).
NO_FIELD_ANYWHERE = (
    "Both readers found no field on this page, but no page of this sheet gave a "
    "field, so it is not counted as read"
)


def _not_clean(row: dict) -> str | None:
    """Why a `no_fields` page is NOT counted as read after all, or None. The
    two readers read the text the page has; that proves nothing when the text
    layer was not usable (OCR pending or failed, no text) or when the picture
    reader was needed and could not be asked."""
    if row["ocr_status"] in ("pending", "failed") or row["native_status"] == "empty":
        return (
            "Both readers found no field on this page, but its text layer was "
            "not usable (OCR not done or failed, or no text), so it is not counted as read"
        )
    reason = str(row["vision_reason"] or "")
    if (
        "unavailable" in reason
        or "vision page budget is spent" in reason
        or "no text layer" in reason
    ):
        return (
            "Both readers found no field on this page, but the picture reader "
            "could not be asked about it, so it is not counted as read"
        )
    return None


def read_page_empty(ai_run: dict, page: int) -> bool:
    """Order 165: did the AI reader READ this page and put nothing forward on
    it? True only when the page has a reading with no error, no accepted
    reading, no refused proposal (`counts`/`rejected`) and no part left
    unread (`partial`, `cut_off`, `parts`, `partly_read`). A page that was not
    asked, errored, timed out, was stopped by a limit, or on which anything
    was proposed is not empty: a reader that failed has said nothing about
    the page."""
    out = (ai_run.get("pages") or {}).get(page)
    return (
        out is not None
        and page not in (ai_run.get("reasons") or {})
        and page not in (ai_run.get("partly_read") or {})
        and not any(
            out.get(k)
            for k in (
                "error",
                "accepted",
                "rejected",
                "counts",
                "partial",
                "cut_off",
                "parts",
                "stopped",
                "merge_rejected",
                "merge_counts",
            )
        )
    )


def no_fact(
    ai_run: dict | None, page: int, reason: str, dropped: dict[str, int]
) -> tuple[str, int, str]:
    """The ledger outcome of a page the code readers gave no fact: READ_NO_FIELD
    when the AI reader read it and put nothing forward (two readers looked), else
    `no_facts` - not read into fields - with `reason` as before."""
    if ai_run is not None and read_page_empty(ai_run, page):
        from . import page_reason_words

        return (READ_NO_FIELD, 0, page_reason_words.no_field_found(dropped))
    return ("no_facts", 0, reason)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _role(conn, document_id: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT document_role FROM document_classification WHERE document_id = ?",
            (document_id,)).fetchone()
    except Exception as exc:  # noqa: BLE001 - a database without classification yet
        return errors.fell_back("page_ledger: no role table yet", exc, None)
    return row["document_role"] if row else None


def refresh(document_id: str, *, as_submittal: bool | None = None) -> int:
    """Rebuild every row of one document from the stage tables. Returns rows.

    Idempotent. The `facts_*` columns written by extraction are kept; every
    other column is recomputed. A page past `page_count` that an earlier
    ledger held is removed, so the ledger never claims a page the file lacks.

    `as_submittal=True` from the callers that are treating the document AS a
    submittal whatever its role label says - fact extraction and a review.
    Without it an unlabelled submittal's pages read `not_applicable`, and a
    review would count none of them as unread.
    """
    conn = connect()
    doc = conn.execute(
        "SELECT page_count, sha256 FROM documents WHERE id = ?", (document_id,)).fetchone()
    if doc is None:
        return 0
    page_count = doc["page_count"] or 0
    pages = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, char_count, needs_ocr, ocr_route FROM pages WHERE document_id = ?",
        (document_id,))}
    # Pages known to the stage tables beyond page_count still get a row: a
    # page that exists anywhere must be accounted for.
    numbers = set(range(1, page_count + 1)) | set(pages)
    ocr = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, engine, mean_conf, low_conf_boxes, seconds, error FROM page_ocr"
        " WHERE document_id = ?",
        (document_id,))}
    covered: dict[int, list[bool]] = {}
    chunk_pages: dict[str, range] = {}
    for c in conn.execute(
            "SELECT id, page_start, page_end, retrievable FROM chunks WHERE document_id = ?",
            (document_id,)):
        span = range(c["page_start"], (c["page_end"] or c["page_start"]) + 1)
        chunk_pages[c["id"]] = span
        for p in span:
            covered.setdefault(p, []).append(bool(c["retrievable"]))
    page_rules: dict[int, list[str]] = {}
    chunk_rules: dict[int, list[str]] = {}
    for e in conn.execute(
            "SELECT scope, page_start, page_end, chunk_id, rule FROM exclusions"
            " WHERE document_id = ?", (document_id,)):
        if e["scope"] == "page" and e["page_start"] is not None:
            for p in range(e["page_start"], (e["page_end"] or e["page_start"]) + 1):
                page_rules.setdefault(p, []).append(e["rule"])
        elif e["scope"] == "chunk":
            span = chunk_pages.get(e["chunk_id"]) or (
                range(e["page_start"], (e["page_end"] or e["page_start"]) + 1)
                if e["page_start"] is not None else range(0))
            for p in span:
                chunk_rules.setdefault(p, []).append(e["rule"])
    any_chunks = bool(chunk_pages)

    is_submittal = (as_submittal if as_submittal is not None
                    else _role(conn, document_id) == SUBMITTAL_ROLE)
    recorded = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, facts_status, facts_count, facts_reason, extractor_version"
        " FROM page_ledger WHERE document_id = ? AND facts_recorded_by = 'extraction'",
        (document_id,))}
    # THE REAL, PER-PAGE `vision_route` DECISION - see `record_fact_pages`'s
    # `vision` argument. Read back BEFORE the DELETE below, exactly like
    # `recorded` (facts) above, so a refresh preserves what extraction found
    # rather than overwriting it with a placeholder.
    recorded_vision = {r["page_no"]: r for r in conn.execute(
        "SELECT page_no, vision_status, vision_reason FROM page_ledger"
        " WHERE document_id = ? AND vision_recorded_by = 'extraction'",
        (document_id,))}
    fact_counts: dict[int, int] = {}
    if is_submittal:
        try:
            for r in conn.execute(
                    "SELECT page, COUNT(*) AS n FROM submittal_facts"
                    " WHERE submittal_document_id = ? AND superseded_at IS NULL"
                    " GROUP BY page", (document_id,)):
                fact_counts[r["page"]] = r["n"]
        except Exception as exc:  # noqa: BLE001 - no submittal tables yet
            fact_counts = errors.fell_back("page_ledger: no facts yet", exc, {})

    now = _now()
    rows = []
    for p in sorted(numbers):
        page = pages.get(p)
        if page is None:
            native_status, native_chars = "not_extracted", None
        elif page["needs_ocr"]:
            native_status, native_chars = "needs_ocr", page["char_count"]
        elif page["char_count"]:
            native_status, native_chars = "text", page["char_count"]
        else:
            native_status, native_chars = "empty", 0

        o = ocr.get(p)
        # The routing reason says WHY the page was or was not sent to
        # recognition (audit F6); a failure replaces it with what went wrong
        # (audit F7) - the page is then unread, and says so.
        ocr_reason = page["ocr_route"] if page is not None else None
        if o is not None and o["error"]:
            ocr_status, ocr_reason = "failed", f"recognition failed: {o['error']}"
        elif o is not None:
            ocr_status = "done"
        elif page is not None and page["needs_ocr"]:
            ocr_status = "pending"
        else:
            ocr_status = "not_required"

        flags = covered.get(p)
        if flags and any(flags):
            index_status, index_reason = "retrievable", None
        elif p in page_rules:
            index_status, index_reason = "excluded", ",".join(sorted(set(page_rules[p])))
        elif flags:
            index_status = "not_retrievable"
            index_reason = ",".join(sorted(set(chunk_rules.get(p, [])))) or "quality_gate"
        elif any_chunks:
            index_status, index_reason = "no_chunk", "no chunk covers this page"
        else:
            index_status, index_reason = "not_chunked", None

        if not is_submittal:
            facts = ("not_applicable", None, None, None, None)
        elif p in recorded and recorded[p]["facts_status"] != "facts" and fact_counts.get(p):
            # A page that HAS recorded current facts is a page read into
            # fields, whatever an older extraction wrote (honesty audit entry
            # 68: pages with facts from the geometry/vision reader read
            # "no_facts"). Derived, so the next refresh recomputes it from the
            # facts rather than keeping this verdict if they are superseded.
            r = recorded[p]
            facts = ("facts", fact_counts[p], None, "derived", r["extractor_version"])
        elif p in recorded:
            r = recorded[p]
            facts = (r["facts_status"], r["facts_count"], r["facts_reason"],
                     "extraction", r["extractor_version"])
        elif fact_counts.get(p):
            facts = ("facts", fact_counts[p], None, "derived", None)
        elif index_status != "retrievable":
            facts = ("not_reached", 0,
                     f"no retrievable chunk covers this page ({index_status}"
                     f"{': ' + index_reason if index_reason else ''}), so fact "
                     "extraction never saw it", "derived", None)
        elif not fact_counts:
            facts = ("not_run", 0, "fact extraction has recorded no result for "
                     "this document", "derived", None)
        else:
            facts = ("no_facts", 0, "no field was read from this page; the parse "
                     "reason was not recorded (read before the page ledger existed)",
                     "derived", None)

        if p in recorded_vision:
            vision_status = recorded_vision[p]["vision_status"]
            vision_reason = recorded_vision[p]["vision_reason"]
        elif not settings.geometry_reader_enabled:
            vision_status, vision_reason = "not_attempted", VISION_NOT_RECORDED_OFF
        else:
            vision_status, vision_reason = "not_attempted", VISION_NOT_RECORDED_STALE

        vision_recorded_by = "extraction" if p in recorded_vision else None
        rows.append((document_id, p, doc["sha256"], native_status, native_chars,
                     ocr_status, ocr_reason, o["engine"] if o else None,
                     o["mean_conf"] if o else None,
                     o["low_conf_boxes"] if o else None, o["seconds"] if o else None,
                     index_status, index_reason, vision_status, vision_reason,
                     vision_recorded_by, *facts, now))

    with conn:
        conn.execute("DELETE FROM page_ledger WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO page_ledger
                   (document_id, page_no, file_sha256, native_status, native_chars,
                    ocr_status, ocr_reason, ocr_engine, ocr_mean_conf,
                    ocr_low_conf_boxes, ocr_seconds,
                    index_status, index_reason, vision_status, vision_reason,
                    vision_recorded_by,
                    facts_status, facts_count, facts_reason, facts_recorded_by,
                    extractor_version, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    return len(rows)


def record_fact_pages(conn, document_id: str, outcomes: dict[int, tuple],
                      *, extractor_version: str | None,
                      vision: dict[int, tuple[str, str]] | None = None) -> None:
    """Fact extraction's own per-page outcome, written in ITS transaction.

    `outcomes` maps page -> (status, count, reason). Every earlier recorded
    outcome of the document is cleared first: a page this extraction did not
    see must not keep the verdict of one that did. `refresh` fills the other
    columns afterwards.

    `vision` (2026-09-27) maps page -> (vision_status, vision_reason) - the
    REAL `datasheets.vision_route` decision for a page, when the geometry/
    vision reader ran at all. Cleared and recorded the same way as `outcomes`,
    on its own `vision_recorded_by` marker so `refresh` can tell "this page's
    vision routing was actually decided this run" from "nothing has ever
    recorded one" and stop reporting the latter as if it were the former.
    """
    now = _now()
    conn.execute(
        "UPDATE page_ledger SET facts_recorded_by = NULL WHERE document_id = ?",
        (document_id,))
    for page, (status, count, reason) in sorted(outcomes.items()):
        conn.execute(
            """INSERT INTO page_ledger
                   (document_id, page_no, facts_status, facts_count, facts_reason,
                    facts_recorded_by, extractor_version, updated_at)
               VALUES (?,?,?,?,?,'extraction',?,?)
               ON CONFLICT(document_id, page_no) DO UPDATE SET
                   facts_status = excluded.facts_status,
                   facts_count = excluded.facts_count,
                   facts_reason = excluded.facts_reason,
                   facts_recorded_by = 'extraction',
                   extractor_version = excluded.extractor_version,
                   updated_at = excluded.updated_at""",
            (document_id, page, status, count, reason, extractor_version, now))
    if vision is not None:
        conn.execute(
            "UPDATE page_ledger SET vision_recorded_by = NULL WHERE document_id = ?",
            (document_id,))
        for page, (vision_status, vision_reason) in sorted(vision.items()):
            conn.execute(
                """INSERT INTO page_ledger
                       (document_id, page_no, vision_status, vision_reason,
                        vision_recorded_by, updated_at)
                   VALUES (?,?,?,?,'extraction',?)
                   ON CONFLICT(document_id, page_no) DO UPDATE SET
                       vision_status = excluded.vision_status,
                       vision_reason = excluded.vision_reason,
                       vision_recorded_by = 'extraction',
                       updated_at = excluded.updated_at""",
                (document_id, page, vision_status, vision_reason, now))


# ------------------------------------------------- PF3 (#883): reading coverage
#
# A PAGE THE AI READER DID NOT READ IS NOT A CLEAN PAGE. The ledger says a page
# was read into fields when the CODE readers found fields on it, and that stays
# true. But when an AI reader was asked to read the sheet and timed out, was
# unavailable or failed on a page, the review has not read that page the way
# the run said it would: "the code readers' reading stands" is a statement
# about the code readers, and a run that carries it has to say so. PF1's first
# run: the local model timed out on 4 of 5 pages of the PSV sheet and the run
# presented itself like any other.
#
# Pure: it reads the reader's own stored summary, never a database.

READING_COMPLETE = "complete"
READING_INCOMPLETE = "incomplete"


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
    if reader and total:
        engine = reader.get("engine") or "AI"
        reasons: dict[int, str] = {}
        for page in reader.get("timed_out") or []:
            reasons[int(page)] = f"the {engine} reader timed out on this page"
        code_only = reader.get("code_only")
        if isinstance(code_only, dict):
            for page, why in code_only.items():
                reasons.setdefault(int(page), f"the {engine} reader did not read this page ({why})")
        for page in reader.get("cut_off") or []:
            reasons.setdefault(int(page), f"the {engine} reader was cut off before this page")
        # order 139: a page the AI read only in part is not a clean page.
        for page, why in (reader.get("partly_read") or {}).items():
            reasons.setdefault(
                int(page), f"the {engine} reader read this page in part ({why})"
            )
        if reader.get("unavailable"):
            for page in range(1, int(total) + 1):
                reasons.setdefault(page, f"the {engine} reader was unavailable ({reader['unavailable']})")
        if reader.get("stopped"):
            read = int(reader.get("pages_read") or 0)
            if read < int(total):
                for page in range(1, int(total) + 1):
                    reasons.setdefault(page, f"the {engine} reader was stopped ({reader['stopped']})")
        ai_missing = {p: why for p, why in sorted(reasons.items()) if 1 <= p <= int(total)}
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


# ------------------------------------------- order 127: one unread-pages count
#
# ONE FACT ON ONE SCREEN HAS ONE SOURCE. The comment sheet's header, its footer
# and "Before you sign" each named the run's unread pages from different keys
# of the same stored record, and disagreed (5 pages, 2 pages, 11 pages). A page
# of a run is "not read" when the run's stored record says some reader the run
# was set to use did not read it: the code readers read no value from it
# (`pages_not_read_into_fields`), or the configured AI reader did not read it
# (`pages_ai_not_read`, PF3 #883). A run stored before `pages_ai_not_read`
# existed (12-14 Oct 2026) also counts the AI reader's own `timed_out` pages.
#
# Pure: it reads the record it is given, never a database.


def every_page_read(pages: dict, where: str, total: int) -> str:
    """What `comparison.qualify_by_pages` says when no page is unread: fields
    were read from `where` of `total`, and (order 165) any page both readers
    read and found no field on is named as that, never counted as a page
    fields were read from."""
    none = pages.get("pages_read_no_field") or []
    if not none:
        return f"fields were read from every page ({where} of {total})"
    return (f"every page was read: fields from {where} of {total}; "
            f"page{'s' if len(none) != 1 else ''} {page_list(none)} "
            "read, no checklist field found")


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
    pages = {int(p) for p in cov.get("pages_not_read_into_fields") or []}
    pages |= {int(p) for p in cov.get("pages_ai_not_read") or []}
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
        **{str(k): v for k, v in (cov.get("not_read_reasons") or {}).items()},
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


def run_unread_pages_shown(
    page_coverage: dict | None, reader: dict | None = None
) -> list[int] | None:
    """The list as a screen shows it: None (not known, rendered as nothing)
    when the run stored no page coverage or no page total; otherwise
    `run_unread_pages`, where [] means every page was read."""
    if not isinstance(page_coverage, dict) or page_coverage.get("pages_total") is None:
        return None
    return run_unread_pages(page_coverage, reader)


def run_unread_pages_of(outcome: dict | None) -> list[int] | None:
    """`run_unread_pages_shown` for a run's stored outcome: its page coverage
    and its reader record. One call for the run summary and the runs list."""
    return run_unread_pages_shown(
        (outcome or {}).get("page_coverage"), run_reader(outcome)
    )


def rows(document_id: str) -> list[dict]:
    return [
        dict(r)
        for r in connect().execute(
            "SELECT * FROM page_ledger WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]


def coverage(document_id: str) -> dict:
    """The per-document summary a review states, WITH ITS DENOMINATOR.

    `pages_total` is None when the ledger holds no row for the document -
    nothing was accounted for, which is not the same as zero pages.
    """
    ledger = rows(document_id)
    if not ledger:
        return {
            "pages_total": None,
            "fact_pages": [],
            "pages_not_read_into_fields": [],
            "pages_read_no_field": [],
            "pages_read_only_by_page_reader": [],
            "not_read_reasons": {},
            "index": {},
            "ocr": {},
            "native": {},
            "facts_source": None,
        }
    count = lambda key: {  # noqa: E731
        v: sum(1 for r in ledger if r[key] == v) for v in sorted({r[key] for r in ledger})}
    not_read = [r for r in ledger if r["facts_status"] in NOT_READ_INTO_FIELDS]
    fact_pages = [r["page_no"] for r in ledger if r["facts_status"] == "facts"]
    no_field, demoted = [], {}
    for r in ledger:
        if r["facts_status"] == READ_NO_FIELD:
            why = _not_clean(r) if fact_pages else NO_FIELD_ANYWHERE
            if why:
                demoted[str(r["page_no"])] = why
                not_read.append(r)
            else:
                no_field.append(r["page_no"])
    sources = {r["facts_recorded_by"] for r in ledger if r["facts_recorded_by"]}
    return {
        "pages_total": len(ledger),
        "native": count("native_status"),
        "ocr": count("ocr_status"),
        "index": count("index_status"),
        "facts": count("facts_status"),
        "fact_pages": fact_pages,
        "pages_read_only_by_page_reader": _page_reader_only(document_id, fact_pages),
        "pages_not_read_into_fields": [r["page_no"] for r in not_read],
        "not_read_reasons": {
            str(r["page_no"]): demoted.get(str(r["page_no"])) or r["facts_reason"]
            for r in not_read
        },
        "pages_read_no_field": no_field,
        "facts_source": (sources.pop() if len(sources) == 1
                         else "mixed" if sources else None),
    }


def _page_reader_only(document_id: str, fact_pages: list[int]) -> list[int]:
    """The read pages whose current facts include none from a rule/text
    reader - read only by the geometry, vision or model reader."""
    if not fact_pages:
        return []
    try:
        methods: dict[int, set[str]] = {}
        for r in connect().execute(
                "SELECT page, extraction_method FROM submittal_facts"
                " WHERE submittal_document_id = ? AND superseded_at IS NULL",
                (document_id,)):
            methods.setdefault(r["page"], set()).add(r["extraction_method"] or "")
    except Exception as exc:  # noqa: BLE001 - no submittal tables yet
        return errors.fell_back("page_ledger: no fact methods yet", exc, [])
    return [p for p in fact_pages
            if methods.get(p) and not (methods[p] & TEXT_READER_METHODS)]


def page_list(pages: list[int]) -> str:
    """`[1, 2, 3, 7]` -> `1-3, 7`: short enough to sit in a finding."""
    out: list[str] = []
    run: list[int] = []
    for p in sorted(pages):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


#: #1017: what a READ of the ledger may rely on. A GET never rebuilds it (a
#: GET writes nothing, #478); it says which of these holds instead.
CURRENT, MISSING, STALE, NOT_AS_SUBMITTAL = "current", "missing", "stale", "not_as_submittal"
STATE_NOTES = {
    MISSING: "the page ledger for this document is not built yet; reading the sheet "
             "into fields or running a review builds it",
    STALE: "the page ledger was built for an earlier file or page count; the next "
           "read of the sheet into fields or review rebuilds it",
    NOT_AS_SUBMITTAL: "the page ledger was built before this document was treated as a "
                      "submittal; reading the sheet into fields or running a review "
                      "rebuilds it with the pages read into fields",
}


def state(document_id: str) -> str:
    """READ ONLY: whether the stored ledger is the one a reader may count on.

    `current`: one row per page of the stored file, built for this file.
    `missing`: no row. `stale`: rows for another file hash or page count.
    `not_as_submittal`: rows built with no fact columns (the document was not
    treated as a submittal when they were built), so "pages read into
    fields" would read as none when nobody has looked.
    """
    conn = connect()
    doc = conn.execute("SELECT page_count, sha256 FROM documents WHERE id = ?",
                       (document_id,)).fetchone()
    ledger = rows(document_id)
    if not ledger:
        return MISSING
    page_count = (doc["page_count"] if doc else None) or 0
    if page_count and len(ledger) != page_count:
        return STALE
    if doc and any(r["file_sha256"] and r["file_sha256"] != doc["sha256"] for r in ledger):
        return STALE
    if all(r["facts_status"] == "not_applicable" for r in ledger):
        return NOT_AS_SUBMITTAL
    return CURRENT


def readiness_pages(document_id: str) -> dict:
    """READ ONLY (#1017): the readiness strip's page numbers, from the stored
    ledger - which a GET never rebuilds; the writers do (ingest, reading the
    sheet into fields, a review). A ledger a reader may not count on is SAID
    in `ledger_state` / `ledger_note`, with no number in its place: null,
    never 0 for "nobody looked" (CLAUDE.md rule 4).

    HONESTY GROUP (2026-09-27): `unread_page_reasons` carries, keyed by the
    page number AS A STRING (a JSON object key), WHY each unread page did not
    read into fields - `coverage`'s own `not_read_reasons`, which the route
    once dropped on the floor.
    """
    ledger_state = state(document_id)
    cov = coverage(document_id) if ledger_state == CURRENT else {}
    return {
        "pages_total": cov.get("pages_total"),
        "pages_read": len(cov.get("fact_pages") or []) if ledger_state == CURRENT else None,
        "pages_read_no_field": cov.get("pages_read_no_field") or [],
        "unread_pages": cov.get("pages_not_read_into_fields") or [],
        "unread_page_reasons": cov.get("not_read_reasons") or {},
        "ledger_state": ledger_state,
        "ledger_note": STATE_NOTES.get(ledger_state),
    }
