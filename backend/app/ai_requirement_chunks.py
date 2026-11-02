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

Slice 4, behind `settings.ai_requirement_extraction_resume_enabled`: a run
reads only chunks THIS model has not read yet (`ai_requirement_chunk_reads`),
so the next run carries on where the last stopped instead of reading the same
first chunks again; a chunk with a passage the model could not read is not
marked and is read again, at most `MAX_ATTEMPTS` times, then given up (it
waits for another model or task version; counted). Marks are per model AND
task version: a different model, or a changed prompt, reads every chunk
afresh; a provider with no model name marks nothing. The answer says how many
of the standard's chunks this model has still to read, and how many it gave
up on. OFF: the first `max_chunks` chunks, every run, as before.

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
    #: slice 4, resume switch on only (else null; null too for a standard with
    #: no chunks, or a model with no name). `standard_chunks`: the chunks OF
    #: THIS STANDARD. Of those, FOR THIS MODEL (and task version):
    #: `not_yet_read` still to read after this run; `gave_up` failed to read
    #: whole `MAX_ATTEMPTS` times, skipped until another model or version.
    standard_chunks: int | None = None
    not_yet_read: int | None = None
    gave_up: int | None = None


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


quote_page = tables.quote_page
_page_texts = tables.page_texts


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


#: A chunk this model and task version failed to read whole this many times is
#: given up (counted as `gave_up`) so it cannot hold a run in place: with answer
#: reuse the same reply would come back every time. It waits for another model
#: or a new task version.
MAX_ATTEMPTS = 2


def ensure_reads_schema() -> None:
    """Slice 4's read marks: one row per (chunk, model, task version). A row
    goes with its standard's document and with its chunk (re-ingest)."""
    from .db import connect

    conn = connect()
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ai_requirement_chunk_reads ("
            " chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,"
            " standard_document_id TEXT NOT NULL"
            " REFERENCES documents(id) ON DELETE CASCADE,"
            " model TEXT NOT NULL, task_version TEXT NOT NULL,"
            " read_whole INTEGER NOT NULL DEFAULT 0,"
            " failed_reads INTEGER NOT NULL DEFAULT 0,"
            " read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " PRIMARY KEY (chunk_id, model, task_version))"
        )


def _task_version() -> str:
    return f"{air.TASK.name}:{air.TASK.version}"


_MARKS = (
    "SELECT chunk_id FROM ai_requirement_chunk_reads WHERE standard_document_id = ?"
    " AND model = ? AND task_version = ?"
)
#: chunks of a standard this model (and task version) has neither read whole
#: nor given up on (slice 4)
_UNREAD = (
    " FROM chunks WHERE document_id = ? AND id NOT IN ("
    + _MARKS
    + " AND (read_whole = 1 OR failed_reads >= ?))"
)
_GAVE_UP = (
    "SELECT COUNT(*) FROM chunks WHERE document_id = ? AND id IN ("
    + _MARKS
    + " AND read_whole = 0 AND failed_reads >= ?)"
)


def _mark(
    conn, chunk_id: str, standard_document_id: str, reader: str, whole: bool
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO ai_requirement_chunk_reads (chunk_id, standard_document_id,"
            " model, task_version, read_whole, failed_reads) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (chunk_id, model, task_version) DO UPDATE SET"
            " read_whole = MAX(read_whole, excluded.read_whole),"
            " failed_reads = failed_reads + excluded.failed_reads,"
            " read_at = CURRENT_TIMESTAMP",
            (
                chunk_id,
                standard_document_id,
                reader,
                _task_version(),
                int(whole),
                int(not whole),
            ),
        )


def _chunks_to_read(conn, keys, standard_document_id: str, max_chunks: int):
    """The chunks this run reads: with read marks (`keys`), those this model
    and task version have neither read whole nor given up on; else the first."""
    if keys:
        ensure_reads_schema()
        return conn.execute(
            "SELECT id, page_start, page_end, text"
            + _UNREAD
            + " ORDER BY ordinal LIMIT ?",
            (*keys, max(max_chunks, 0)),
        ).fetchall()
    return conn.execute(
        "SELECT id, page_start, page_end, text FROM chunks WHERE document_id = ?"
        " ORDER BY ordinal LIMIT ?",
        (standard_document_id, max(max_chunks, 0)),
    ).fetchall()


def _resume_counts(conn, keys, report: dict) -> None:
    """Of THIS standard's chunks, FOR THIS model and task version: how many are
    left and how many were given up. A standard with no chunks: null, never
    "0 of 0 left"."""
    total = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (keys[0],)
    ).fetchone()[0]
    if total:
        report["standard_chunks"] = total
        report["not_yet_read"] = conn.execute(
            "SELECT COUNT(*)" + _UNREAD, keys
        ).fetchone()[0]
        report["gave_up"] = conn.execute(_GAVE_UP, keys).fetchone()[0]


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
        "standard_chunks": None,
        "not_yet_read": None,
        "gave_up": None,
    }
    if (
        not settings.ai_requirement_extraction_enabled
        or standard_document_id not in allowed_document_ids
    ):
        return report
    conn = connect()
    provider = provider or ai_task_runner.make_provider()
    report["model"] = getattr(provider, "requested_model", None)
    reader = report["model"]
    # no model name: nothing can say which model read a chunk, so nothing is
    # marked and the run reads the first chunks, as with the switch off
    resume = bool(settings.ai_requirement_extraction_resume_enabled) and bool(reader)
    keys = (
        standard_document_id,
        standard_document_id,
        reader,
        _task_version(),
        MAX_ATTEMPTS,
    )
    chunks = _chunks_to_read(
        conn, keys if resume else None, standard_document_id, max_chunks
    )
    air.ensure_schema()
    with heavy_lock.held("ai_batch", owner="requirement extraction", wait_seconds=0):
        try:
            for chunk in chunks:
                report["chunks"] += 1
                found = air.extract(chunk["text"], provider=provider)
                report["could_not_read"] += len(found["could_not_read"])
                for item in found["requirements"]:
                    _take(conn, standard_document_id, chunk, item, report)
                if resume:
                    _mark(
                        conn,
                        chunk["id"],
                        standard_document_id,
                        reader,
                        not found["could_not_read"],
                    )
        finally:
            (unload or ai_task_runner._unload)(provider)
    if resume:
        _resume_counts(conn, keys, report)
    return report
