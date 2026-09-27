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

from .config import settings
from .db import connect

SUBMITTAL_ROLE = "CONTRACTOR_SUBMITTAL"

#: Fact statuses that mean "no field was read from this page". A page in one
#: of these states was NOT searched for values, so a review may not say the
#: contractor omitted a value it could hold.
NOT_READ_INTO_FIELDS = frozenset({"no_facts", "unreadable", "not_reached", "not_run"})
#: The rule/text readers' extraction methods. A page whose current facts all
#: came from any OTHER reader (geometry, vision, model) is read - the ledger
#: says "facts" - but an ABSENCE there is not the contractor's omission: the
#: page reader is not known to read every field on a page, so a value it did
#: not find may still be printed there (owner decision 2026-09-26; honesty
#: audit entry 68). An allow-list, so a new reader defaults to the cautious side.
TEXT_READER_METHODS = frozenset({"extracted", "ocr_fallback", "grid"})

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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _role(conn, document_id: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT document_role FROM document_classification WHERE document_id = ?",
            (document_id,)).fetchone()
    except Exception:  # noqa: BLE001 - a database without classification yet
        return None
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
        "SELECT page_no, engine, mean_conf, seconds, error FROM page_ocr"
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
        except Exception:  # noqa: BLE001 - no submittal tables yet
            fact_counts = {}

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
                     o["mean_conf"] if o else None, o["seconds"] if o else None,
                     index_status, index_reason, vision_status, vision_reason,
                     vision_recorded_by, *facts, now))

    with conn:
        conn.execute("DELETE FROM page_ledger WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO page_ledger
                   (document_id, page_no, file_sha256, native_status, native_chars,
                    ocr_status, ocr_reason, ocr_engine, ocr_mean_conf, ocr_seconds,
                    index_status, index_reason, vision_status, vision_reason,
                    vision_recorded_by,
                    facts_status, facts_count, facts_reason, facts_recorded_by,
                    extractor_version, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
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


def rows(document_id: str) -> list[dict]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM page_ledger WHERE document_id = ? ORDER BY page_no", (document_id,))]


def coverage(document_id: str) -> dict:
    """The per-document summary a review states, WITH ITS DENOMINATOR.

    `pages_total` is None when the ledger holds no row for the document -
    nothing was accounted for, which is not the same as zero pages.
    """
    ledger = rows(document_id)
    if not ledger:
        return {"pages_total": None, "fact_pages": [], "pages_not_read_into_fields": [],
                "pages_read_only_by_page_reader": [],
                "not_read_reasons": {}, "index": {}, "ocr": {}, "native": {},
                "facts_source": None}
    count = lambda key: {  # noqa: E731
        v: sum(1 for r in ledger if r[key] == v) for v in sorted({r[key] for r in ledger})}
    not_read = [r for r in ledger if r["facts_status"] in NOT_READ_INTO_FIELDS]
    fact_pages = [r["page_no"] for r in ledger if r["facts_status"] == "facts"]
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
        "not_read_reasons": {str(r["page_no"]): r["facts_reason"] for r in not_read},
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
    except Exception:  # noqa: BLE001 - no submittal tables yet
        return []
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
