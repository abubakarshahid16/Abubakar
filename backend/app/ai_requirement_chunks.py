"""#645 slice 3: the local model reads a held standard's CHUNKS, code checks every field.

`ai_requirements.propose_checks` only asks about a sentence the parser already
stored (`statement`). A table row, or a requirement the parser did not split
into a sentence, has no such row, so nothing proposed a limit for it. This
module feeds a standard's chunks (tables too) to `ai_requirements.extract`
(passage by passage, the LOCAL model only: `ai_task_runner.make_provider` is
Ollama and nothing here imports `reader_transport`, whatever
`REASONING_PROVIDER` says) and keeps an item only when CODE confirms it:

  * the quote is the chunk's own words (`extract` checks it, again here);
  * value and unit are read from the quote and must agree with the model
    (`ai_requirements.verify_proposal`): no number the quote does not hold;
    `range` and `none` are not single limits and are refused;
  * the COMPARATOR must be stated in the quote's own words (code's reading,
    never the model's say-so; "=" is not a default): otherwise it stays
    unknown and the row is refused and counted;
  * a conditional sentence with no condition is refused;
  * the quote must sit on ONE page (a chunk across pages is refused: a
    citation to the wrong page is worse than none). Slice 3, behind
    `settings.ai_requirement_quote_page_enabled`: the page of such a chunk
    whose OWN text holds the whole quote is the page, when exactly one does
    (none or several: refused, as before); accept checks it there again;
  * a quote an existing requirement already holds is not proposed again.

What passes is stored as a `statement` row for the quote plus a DRAFT in
`clause_check_drafts`, the table the engineer's accept/reject (#869) already
reads. The statement row is HELD (`superseded_at` = HELD, a value every reader
and `auto_use_rules` already exclude) until the engineer accepts, so no review,
count, CRS note or automatic rule sees it before then; `ai_requirements.decide_draft` accepts a
HELD row inside its own one transaction. Nothing here is a verdict. OFF unless
`settings.ai_requirement_extraction_enabled`. Counts only; never a quote.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from . import ai_requirement_tables as tables
from . import ai_requirements as air
from . import ai_task_runner, heavy_lock
from .config import settings


class ExtractionCounts(BaseModel):
    """The counts-only answer of the extract route (never a quote). Kept here,
    not in `schemas.py`, which may only shrink."""

    enabled: bool
    chunks: int
    proposed: int
    refused: dict[str, int]
    could_not_read: int
    model: str | None = None


NOT_A_SINGLE_LIMIT = "the requirement is not a single limit with a comparator"
MODEL_FLAGGED = "code's reading and the model's disagree"
COMPARATOR_NOT_STATED = tables.COMPARATOR_NOT_STATED
PAGE_UNCERTAIN = "the chunk spans pages, so the quote's page is not certain"
ALREADY_HELD = "an existing requirement already holds these words"
#: `superseded_at` of a row waiting for the engineer's decision on its draft.
HELD = "held:ai_requirement_extraction"  # the same literal as `ai_requirements._draft`
_SINGLE = {"<=", "<", ">=", ">", "="}
_PIECES = re.compile(r"(?<=[.;])\s+|\n+")


def _enclosing(quote: str, chunk_text: str) -> str:
    """The sentence (or table line) of the chunk that holds the quote; the
    quote itself when it spans several."""
    for piece in _PIECES.split(chunk_text):
        if air._squash(quote) in air._squash(piece):
            return piece
    return quote


def _held(conn, standard_document_id: str, quote: str) -> bool:
    needle = air._squash(quote)
    for row in conn.execute(
        "SELECT source_text, requirement_text FROM standard_requirements"
        " WHERE standard_document_id = ? AND (superseded_at IS NULL OR superseded_at = ?)",
        (standard_document_id, HELD),
    ):
        if needle in air._squash(row["source_text"] or row["requirement_text"] or ""):
            return True
    return False


def verify_item(item: dict, chunk_text: str) -> tuple[dict | None, str | None]:
    """(check, None) when code confirms the extracted item as ONE limit, else
    (None, why)."""
    if item.get("flags"):
        return None, MODEL_FLAGGED
    if item.get("operator") not in _SINGLE:
        return None, NOT_A_SINGLE_LIMIT
    proposal = {
        "has_limit": True,
        "field": item.get("subject"),
        "operator": item.get("operator"),
        "value": item.get("value"),
        "unit": item.get("unit"),
        "condition": item.get("condition"),
        "quote": item.get("quote"),
    }
    check, why = air.verify_proposal(
        proposal, _enclosing(item.get("quote") or "", chunk_text)
    )
    if check is None:
        return None, why
    stated = {f["operator"] for f in air.read_figures(check["quote"]) if f["operator"]}
    if check["operator"] not in stated:
        return None, COMPARATOR_NOT_STATED
    return check, None


def _page_texts(conn, standard_document_id: str, chunk) -> dict[int, str]:
    return {
        r["page_no"]: r["text"] or ""
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?"
            " AND page_no BETWEEN ? AND ? ORDER BY page_no",
            (standard_document_id, chunk["page_start"], chunk["page_end"]),
        )
    }


def quote_page(quote: str, texts: dict[int, str]) -> int | None:
    """The ONE page whose own text holds the whole quote; None when no page
    (the quote crosses a page break) or several do."""
    hits = [no for no, text in texts.items() if tables.quote_on_page(quote, text)]
    return hits[0] if len(hits) == 1 else None


def _table_row(item: dict, chunk, texts: dict[int, str], resolve: bool):
    """`tables.read_row` with the page its quote is on: (checks, refusals,
    page) or None (not a table row). `resolve` off: the chunk's first page,
    as before. On (a chunk across pages): the ONE page that holds every cell
    of the quote in reading order; none or several: refused, page uncertain."""
    first = chunk["page_start"]
    if not resolve:
        row = tables.read_row(item, chunk["text"], texts.get(first))
        return None if row is None else (*row, first)
    base = tables.read_row(item, chunk["text"], None)  # the page plays no part in None
    if base is None or base[1] != [tables.CELLS_NOT_ON_PAGE]:
        return None if base is None else (*base, first)
    found = [
        (no, tables.read_row(item, chunk["text"], text)) for no, text in texts.items()
    ]
    on = [(no, row) for no, row in found if tables.CELLS_NOT_ON_PAGE not in row[1]]
    if len(on) != 1:
        return [], [PAGE_UNCERTAIN], None
    no, (checks, refusals) = on[0]
    return checks, refusals, no


def _refuse(report: dict, why: str) -> None:
    report["refused"][why] = report["refused"].get(why, 0) + 1


def _store(
    conn, standard_document_id: str, chunk, check: dict, model, version, page
) -> None:
    from . import standards

    row = standards.create_requirement(
        standard_document_id=standard_document_id,
        chunk_id=chunk["id"],
        requirement_text=check["quote"],
        source_text=check["quote"],
        clause=None,
        page=page,
        extraction_method="extracted",
        extractor_version=version,
        structured={"requirement_type": air.STATEMENT},
    )
    with conn:
        conn.execute(
            "UPDATE standard_requirements SET superseded_at = ? WHERE id = ?",
            (HELD, row["id"]),
        )
        conn.execute(
            "INSERT OR IGNORE INTO clause_check_drafts (id, requirement_id, field,"
            " operator, value, unit, condition, quote, model)"
            " VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                check["field"],
                check["operator"],
                check["value"],
                check["unit"] or "",
                check["condition"],
                check["quote"],
                model,
            ),
        )


def _take(conn, standard_document_id: str, chunk, item: dict, report: dict) -> None:
    """Verify one extracted item and store what passes. A row of a headed
    table whose column header states the direction (slice 2) is read by
    `ai_requirement_tables`; every other item takes the sentence path. A chunk
    across pages: refused, or (slice 3, switch on) cited to the one page whose
    own text holds the quote."""
    split = chunk["page_start"] != chunk["page_end"]
    resolve = split and bool(settings.ai_requirement_quote_page_enabled)
    texts = _page_texts(conn, standard_document_id, chunk)
    row = _table_row(item, chunk, texts, resolve)
    if row is not None:
        checks, refusals, page = row
        for why in refusals:
            _refuse(report, why)
        duplicate = tables.already_drafted
        version = tables.TABLE_VERSION
    else:
        check, why = verify_item(item, chunk["text"])
        checks = [check] if check else []
        duplicate = lambda c, s, ck: _held(c, s, ck["quote"])  # noqa: E731
        if check is None:
            _refuse(report, why)
        page = quote_page(check["quote"], texts) if check and resolve else None
        version = tables.QUOTE_PAGE_VERSION if page is not None else None
        page = page if resolve else chunk["page_start"]
    for check in checks:
        if page is None or (split and not resolve):
            _refuse(report, PAGE_UNCERTAIN)
        elif duplicate(conn, standard_document_id, check):
            _refuse(report, ALREADY_HELD)
        else:
            _store(
                conn,
                standard_document_id,
                chunk,
                check,
                report["model"],
                version,
                page,
            )
            report["proposed"] += 1


def extract_standard(
    standard_document_id: str,
    *,
    allowed_document_ids: frozenset[str],
    max_chunks: int,
    provider=None,
    unload=None,
) -> dict:
    """Read at most `max_chunks` chunks of ONE standard and store what code
    confirms as HELD drafts. Returns counts only. Switch off, or a standard the
    caller may not read: nothing is read or written. The model calls run under
    the heavy-job lock (`heavy_lock`, kind `ai_batch`) and the model is
    unloaded at the end."""
    from .db import connect

    report = {
        "enabled": bool(settings.ai_requirement_extraction_enabled),
        "chunks": 0,
        "proposed": 0,
        "refused": {},
        "could_not_read": 0,
        "model": None,
    }
    if (
        not settings.ai_requirement_extraction_enabled
        or standard_document_id not in allowed_document_ids
    ):
        return report
    conn = connect()
    chunks = conn.execute(
        "SELECT id, page_start, page_end, text FROM chunks WHERE document_id = ?"
        " ORDER BY ordinal LIMIT ?",
        (standard_document_id, max(max_chunks, 0)),
    ).fetchall()
    air.ensure_schema()
    provider = provider or ai_task_runner.make_provider()
    report["model"] = getattr(provider, "requested_model", None)
    with heavy_lock.held("ai_batch", owner="requirement extraction", wait_seconds=0):
        try:
            for chunk in chunks:
                report["chunks"] += 1
                found = air.extract(chunk["text"], provider=provider)
                report["could_not_read"] += len(found["could_not_read"])
                for item in found["requirements"]:
                    _take(conn, standard_document_id, chunk, item, report)
        finally:
            (unload or ai_task_runner._unload)(provider)
    return report
