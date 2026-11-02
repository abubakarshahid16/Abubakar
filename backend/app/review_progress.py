"""#1494: the progress block of a running review, from the `jobs` row alone.

Read-only: no model call, no socket, no new table. Behind
`REVIEW_PROGRESS_BAR_ENABLED` (off: `review_jobs.job_for_run` adds nothing).
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from pydantic import BaseModel

from . import job_progress, job_queue
from .config import settings
from .db import connect

#: The label `review_jobs._page` writes: "reading the procedure, page 7 of 69",
#: or "part 7 of 69" for a Word file (no fixed pages).
_PAGE_LABEL = re.compile(r", (page|part) (\d+) of (\d+)$")

#: The label `review_jobs._clause` writes: "checking clause 12 of 60".
_CLAUSE_LABEL = re.compile(r"^checking clause (\d+) of (\d+)$")

#: The other labels of a running review (`review_jobs.STEPS`, `.FINISHING`): named
#: as they are, with no claim that a model is being waited on at this moment.
_STEP_LABEL = re.compile(
    r"^(reading the |selecting the |comparing requirements |finishing: )"
)

#: `reasoning_provider.OllamaProvider`'s limit on one call: the slack a step
#: with no finer report gets before its silence is slow.
MODEL_CALL_LIMIT_S = 900

#: Job states in which the block is shown.
ACTIVE_STATES = ("queued", "running", "retrying")


class ReviewProgressDetail(BaseModel):
    """What the progress block shows. A figure the row does not hold is null,
    never 0. Ages are seconds on the SERVER's clock, so the browser's clock
    never decides a stall."""

    pages_done: int | None = None
    pages_total: int | None = None
    #: "page", or "part" for a Word file; null outside the reading step.
    pages_unit: str | None = None
    #: The sub-step the job is on, e.g. "reading page 3 of 5: waiting for the
    #: model" or "comparing requirements with the document"; null when none.
    waiting_on: str | None = None
    clauses_done: int | None = None
    clauses_total: int | None = None
    clauses_elapsed_seconds: int | None = None
    elapsed_seconds: int | None = None
    idle_seconds: int | None = None
    stall_amber_seconds: int = 120
    stale: bool = False


def seconds_since(stamp: str | None) -> int | None:
    """Whole seconds since an ISO stamp; None when absent or unreadable."""
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - then).total_seconds()))


def _model_reads_pages() -> bool:
    from . import datasheet_ai

    return datasheet_ai.engine_setting() != datasheet_ai.OFF


def _beat_age(claimed_by: str | None) -> int | None:
    """Seconds since the last beat of the worker in this process holding the
    claim; None when none does (dead, silent too long, or another process)."""
    from . import ingest

    return ingest.get_worker().beat_age_of_claim(claimed_by)


def _waiting(label, on_page, total, unit, c_on, c_total) -> tuple[str | None, int]:
    """(the sub-step named, its amber threshold). A model sub-step may take the
    model's own time limit before it is slow (the live review: one 35B page set the
    stall light): a page up to two reader calls, a clause one call, any other
    step of a running review one call of the local provider."""
    base = int(settings.review_progress_stall_amber_s)
    if on_page is not None:
        if not _model_reads_pages():
            return f"reading {unit} {on_page} of {total}", base
        allowance = 2 * int(settings.datasheet_ai_timeout_seconds)
        return (
            f"reading {unit} {on_page} of {total}: waiting for the model",
            base + allowance,
        )
    if c_on is not None:
        allowance = int(settings.clause_review_call_timeout_s)
        return (
            f"checking clause {c_on} of {c_total}: waiting for the model",
            base + allowance,
        )
    if _STEP_LABEL.match(label):
        return label, base + MODEL_CALL_LIMIT_S
    return None, base


def detail(row: dict) -> dict:
    """The block for one job row.

    `pages_done` counts FINISHED pages: the reader reports a page when it
    STARTS it ("page 7 of 69"), so 6 are done. Pages are null outside the
    reading step. `idle_seconds` is the time since the job last moved (its
    progress line, its worker claim, or a beat of the worker holding it);
    `stale` is job_queue's claim rule AND no movement for as long AND no live
    worker vouching: model calls beat the worker, never this row, so a frozen
    row alone is not "stuck". A dead or long-silent worker vouches for nothing."""
    match = _PAGE_LABEL.search(row.get("progress_label") or "")
    unit = match.group(1) if match else None
    on_page = int(match.group(2)) if match else None
    total = int(match.group(3)) if match else None
    done = max(0, min(on_page - 1, total)) if total else None
    # Same honest rule as pages: the clause review reports a clause when it
    # STARTS it ("clause 12 of 60"), so 11 are done.
    cm = _CLAUSE_LABEL.match(row.get("progress_label") or "")
    c_on = int(cm.group(1)) if cm else None
    c_total = int(cm.group(2)) if cm else None
    c_done = max(0, min(c_on - 1, c_total)) if c_total else None
    started = job_progress.CLAUSE_STARTED.get(row.get("id") or "")
    c_elapsed = (
        max(0, int(time.time() - started)) if started and c_done is not None else None
    )
    ages = [
        seconds_since(row.get("updated_at")),
        seconds_since(row.get("claimed_at")),
    ]
    beat_age = _beat_age(row.get("claimed_by"))
    ages = [a for a in [*ages, beat_age] if a is not None]
    claim_age = seconds_since(row.get("claimed_at"))
    idle = min(ages) if ages else None
    waiting_on, amber = _waiting(
        row.get("progress_label") or "",
        on_page if done is not None else None,
        total,
        unit,
        c_on if c_done is not None else None,
        c_total,
    )
    return {
        "pages_done": done,
        "pages_total": total if done is not None else None,
        "pages_unit": unit if done is not None else None,
        "waiting_on": waiting_on,
        "clauses_done": c_done,
        "clauses_total": c_total if c_done is not None else None,
        "clauses_elapsed_seconds": c_elapsed,
        "elapsed_seconds": seconds_since(row.get("started_at")),
        "idle_seconds": idle,
        "stall_amber_seconds": amber,
        "stale": (
            claim_age is not None
            and claim_age >= job_queue.CLAIM_STALE_SECONDS
            and idle is not None
            and idle >= job_queue.CLAIM_STALE_SECONDS
            and beat_age is None
        ),
    }


def for_job(job: dict) -> dict | None:
    """The block for a job as `job_for_run` returns it; None when the switch is
    off or the job is no longer active."""
    if not settings.review_progress_bar_enabled:
        return None
    if job.get("state") not in ACTIVE_STATES:
        return None
    row = (
        connect()
        .execute(
            "SELECT started_at, updated_at, claimed_at, claimed_by FROM jobs"
            " WHERE id = ?",
            (job["id"],),
        )
        .fetchone()
    )
    return detail({**job, **(dict(row) if row else {})})
