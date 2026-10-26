"""Read the datasheet again for the standards a review chose (order 211, audit R2).

A review reads the datasheet FIRST and chooses the standards AFTER (the choice
needs the sheet's facts). The form reader asks for the fields the standards'
requirements are about (`form_reader_run.requirement_subjects`), but at the
first read of a new sheet no standard is chosen yet, so those fields were never
asked and every requirement about them came back "not stated".

So, once the standards are chosen: work out which of their fields the last read
did not ask; if there are any, read the sheet ONCE more with them added. Nothing
is invented here: it is the same reader, the same page-quote proof and the same
rules; only the list of fields is longer. One more full model read, so it runs
only when something was never asked, and never twice for the same standards
(the read records the fields it asked, `asked_subjects`).
"""

from __future__ import annotations

import logging
import sqlite3

from . import datasheets, form_reader_run, review_trace
from .config import settings
from .db import connect
from .form_reader_fields import field_list_for, with_requirement_fields

log = logging.getLogger(__name__)


def chosen_standards(run_id: str) -> list[str]:
    """The standards this review run included."""
    try:
        rows = connect().execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1",
            (run_id,),
        )
        return [r["standard_document_id"] for r in rows]
    except sqlite3.Error:
        return []


def _chunks(document_id: str) -> list:
    return (
        connect()
        .execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        )
        .fetchall()
    )


def missing_subjects(document_id: str, standard_ids: list[str]) -> list[str]:
    """The fields the standards ask about that the last read did not ask, as
    the form reader would add them (same de-duplication, same cap). [] when the
    last read was not a model read of the form (nothing to improve), or when
    every field was asked."""
    summary = datasheets.latest_reader_summary(document_id) or {}
    if summary.get("engine") in (None, "off") or summary.get("unavailable"):
        return []
    needed = form_reader_run.requirement_subjects(standard_ids)
    if not needed:
        return []
    base = field_list_for(
        form_reader_run.equipment_type_of(
            document_id, [dict(c) for c in _chunks(document_id)]
        )
    )
    asked = with_requirement_fields(base, list(summary.get("asked_subjects") or []))
    return [f.name for f in with_requirement_fields(asked, needed)[len(asked) :]]


def for_review(
    document_id: str, allowed_document_ids, run_id: str, timings: dict | None = None
) -> dict | None:
    """Read the sheet again when the run's chosen standards ask for fields the
    last read did not. Returns `{"subjects": n}` when it read again, else None;
    the extra read is shown in the job's phase `timings` as `read_again`.
    Only in the form reader's mode with the model reader on. A failure leaves
    the first reading in place (extraction is all-or-nothing) and is logged by
    kind only, never with document text."""
    if (
        form_reader_run.reader_mode() != form_reader_run.FORM
        or str(settings.datasheet_ai_reader or "off").strip().lower() == "off"
    ):
        return None
    standard_ids = chosen_standards(run_id)
    missing = missing_subjects(document_id, standard_ids)
    if not missing:
        return None
    try:
        with (
            form_reader_run.reading_for(standard_ids),
            review_trace.timed(timings if timings is not None else {}, "read_again"),
        ):
            datasheets.extract_facts(
                document_id,
                allowed_document_ids=allowed_document_ids,
                review_run_id=run_id,
                replace=True,
            )
    except Exception as exc:  # noqa: BLE001 - the first reading stays; the review goes on
        log.warning(
            "reading again for the chosen standards failed: %s", type(exc).__name__
        )
        return None
    return {"subjects": len(missing)}
