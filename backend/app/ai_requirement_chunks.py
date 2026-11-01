"""#645 slice 3: the local model reads a held standard's CHUNKS, code checks every field.

`ai_requirements.propose_checks` only asks about a sentence the parser already
stored (`statement`). A table row, or a requirement the parser did not split
into a sentence, has no such row, so nothing proposed a limit for it. This
module feeds a standard's chunks (tables too) to `ai_requirements.extract`
(passage by passage, the LOCAL model only: `ai_task_runner.make_provider` is
Ollama and nothing here imports `reader_transport`, whatever
`REASONING_PROVIDER` says) and keeps an item only when CODE confirms it:

  * the quote is the chunk's own words (`extract` checks it, again here);
  * value, unit and comparator are read from the quote and must agree with
    the model (`ai_requirements.verify_proposal`): no number the quote does not
    hold; `range` and `none` are not single limits and are refused;
  * a conditional sentence with no condition is refused;
  * the quote must sit on ONE page (a chunk across pages is refused: a
    citation to the wrong page is worse than none);
  * a quote an existing requirement already holds is not proposed again.

What passes is stored as a `statement` row for the quote plus a DRAFT in
`clause_check_drafts`, the table the engineer's accept/reject (#869) already
reads. Nothing here is a verdict. OFF unless
`settings.ai_requirement_extraction_enabled`. Counts only; never a quote.
"""

from __future__ import annotations

import re

from . import ai_requirements as air
from . import ai_task_runner
from .config import settings

NOT_A_SINGLE_LIMIT = "the requirement is not a single limit with a comparator"
MODEL_FLAGGED = "code's reading and the model's disagree"
PAGE_UNCERTAIN = "the chunk spans pages, so the quote's page is not certain"
ALREADY_HELD = "an existing requirement already holds these words"
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
        " WHERE standard_document_id = ? AND superseded_at IS NULL",
        (standard_document_id,),
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
    return air.verify_proposal(
        proposal, _enclosing(item.get("quote") or "", chunk_text)
    )


def _refuse(report: dict, why: str) -> None:
    report["refused"][why] = report["refused"].get(why, 0) + 1


def extract_standard(
    standard_document_id: str,
    *,
    allowed_document_ids: frozenset[str],
    max_chunks: int,
    provider=None,
) -> dict:
    """Read at most `max_chunks` chunks of ONE standard and store what code
    confirms as drafts. Returns counts only. Switch off, or a standard the
    caller may not read: nothing is read or written."""
    from . import standards
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
    for chunk in chunks:
        report["chunks"] += 1
        found = air.extract(chunk["text"], provider=provider)
        report["could_not_read"] += len(found["could_not_read"])
        for item in found["requirements"]:
            check, why = verify_item(item, chunk["text"])
            if check is None:
                _refuse(report, why)
            elif chunk["page_start"] != chunk["page_end"]:
                _refuse(report, PAGE_UNCERTAIN)
            elif _held(conn, standard_document_id, check["quote"]):
                _refuse(report, ALREADY_HELD)
            else:
                row = standards.create_requirement(
                    standard_document_id=standard_document_id,
                    chunk_id=chunk["id"],
                    requirement_text=check["quote"],
                    source_text=check["quote"],
                    clause=None,
                    page=chunk["page_start"],
                    extraction_method="extracted",
                    structured={"requirement_type": air.STATEMENT},
                )
                with conn:
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
                            report["model"],
                        ),
                    )
                report["proposed"] += 1
    return report
