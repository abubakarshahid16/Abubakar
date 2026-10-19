"""What an export says about the run it comes from (#633 items 6 and 7).

The review PDF and the CRS are read away from the screen, so each must carry
on itself what the readiness strip shows on screen: WHICH run it is, whether
that run COMPLETED, which pages were NOT read into fields and which cited
standards the library does NOT hold. A run that failed, was cancelled or is
still running is said in those words; it is never printed as a review with
nothing to raise (CLAUDE.md rule 4: absence is never a positive outcome).

Data and wording only. `review.render_report` draws the PDF and
`crs_export.build_crs` the workbook; `main._crs_content` composes the CRS.
"""
from __future__ import annotations

import json

from . import page_ledger
from .db import connect

COMPLETED = "completed"
#: Printed where a run's reason would go when none was stored.
NO_REASON = "no reason was recorded"
#: How many page numbers or standard ids a count is followed by.
LIST_LIMIT = 40


def missing_standards(submittal_id: str, allowed: frozenset[str]) -> list[str]:
    """Standards this submittal CITES that the library does not hold.

    THE ONE ANSWER for the CRS gap rows, the Active Standards tile, the
    readiness strip and the review PDF (CLAUDE.md rule 8). Read from the
    submittal's own chunk text rather than by re-running applicability
    selection. The rule is `applicability.missing_references`, only CALLED
    here: a private copy once compared an identifier against a dict keyed by
    document id, so every cited standard was "missing" and the CRS told a
    contractor that six held standards were unavailable.

    Reported in the submittal's own spelling ("32-SAMSS-004", never
    "32SAMSS004"); ordered by the normalised key so the rows are stable.
    """
    from . import applicability, datasheets  # lazy: both reach back into review

    text = " ".join(
        row["text"] or "" for row in connect().execute(
            "SELECT text FROM chunks WHERE document_id = ?", (submittal_id,)))
    names = datasheets.referenced_standards(text)
    missing = applicability.missing_references(applicability._library(allowed), names)
    return sorted(missing, key=applicability.normalise_identifier)


def latest_run(document_id: str) -> dict | None:
    """The newest review run of this submittal (id, status, stored outcome),
    or None when none was ever started. Ordered as `list_review_runs` orders,
    so "the latest run" means one thing. The caller has already checked the
    document is readable; a run is its submittal's."""
    from . import submittal_review  # lazy: it reaches back into review

    submittal_review.ensure_schema()
    row = connect().execute(
        "SELECT id, status, outcome_json FROM review_runs WHERE submittal_document_id = ?"
        " ORDER BY created_at DESC, id DESC LIMIT 1", (document_id,)).fetchone()
    if row is None:
        return None
    try:
        outcome = json.loads(row["outcome_json"] or "{}")
    except (TypeError, ValueError):
        outcome = {}
    return {"id": row["id"], "status": row["status"] or "unknown",
            "reason": str((outcome if isinstance(outcome, dict) else {}).get("error") or "")}


def incomplete(run: dict | None) -> bool:
    """True for a run that exists and did not complete (failed, cancelled,
    queued, running). No run at all is not an incomplete run."""
    return run is not None and run.get("status") != COMPLETED


def status_line(status: str | None, reason: str | None) -> str:
    """'Run <status>: <reason>' for a run that did not complete; '' for one
    that did. The reason is the run's own stored words, never re-worded."""
    if status == COMPLETED:
        return ""
    return f"Run {status or 'unknown'}: {_reason(reason)}"


def _reason(reason: str | None) -> str:
    return (reason or "").strip().rstrip(".") or NO_REASON


def _listed(values: list, label: str, unit: str) -> str:
    """'<label>: <count> (<ids>)' - a count never without what it counts."""
    items = [str(v) for v in values]
    shown = ", ".join(items[:LIST_LIMIT]) + (
        f" and {len(items) - LIST_LIMIT} more" if len(items) > LIST_LIMIT else "")
    return f"{label}: {len(items)} {unit}" + (f" ({shown})" if items else "")


def unread_pages_line(pages: list, known: bool = True, note: str | None = None) -> str:
    """The unread pages, as the readiness strip counts them. `known` is False
    when the page ledger cannot be counted on: then the line says the count is
    not known rather than printing 0 for "nobody looked"."""
    if not known:
        return "Unread pages: not known" + (f" - {note}" if note else "")
    return _listed(pages, "Unread pages", "page(s) not read into fields")


def missing_standards_line(missing: list[str]) -> str:
    return _listed(missing, "Missing standards", "cited standard(s) not in the library")


def pdf_header_lines(document_id: str, allowed: frozenset[str] | None) -> tuple[dict | None, list[str]]:
    """The run and the lines the review PDF prints under its title: the run
    code and status, the status line of a run that did not complete, the
    unread pages (from the page ledger, as the readiness route reads it) and
    the missing standards. `allowed` None means the caller asked for no
    scoping (scripts, tests): every document counts as held."""
    run = latest_run(document_id)
    if allowed is None:
        allowed = frozenset(r["id"] for r in connect().execute("SELECT id FROM documents"))
    pages = page_ledger.readiness_pages(document_id)
    lines = [f"Review run: {run['id']}  |  Status: {run['status']}" if run
             else "Review run: none recorded for this document"]
    if incomplete(run):
        lines.append(status_line(run["status"], run["reason"]))
    lines.append(unread_pages_line(pages["unread_pages"],
                                   known=pages["ledger_state"] == page_ledger.CURRENT,
                                   note=pages.get("ledger_note")))
    lines.append(missing_standards_line(missing_standards(document_id, allowed)))
    return run, lines


def crs_header_note(status: str | None, reason: str | None,
                    unread: list, missing: list[str]) -> str:
    """The first line of a CRS whose run did not complete: '' for a completed
    run (its sheet is unchanged), else the status, its reason and the same
    two counts the readiness strip shows. Both copies print it."""
    if status == COMPLETED:
        return ""
    return (f"REVIEW INCOMPLETE: run {status or 'unknown'} - {_reason(reason)}. "
            f"{unread_pages_line(unread)}. {missing_standards_line(missing)}.")
