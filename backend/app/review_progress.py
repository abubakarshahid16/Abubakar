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

#: The label `review_jobs._page` writes: "reading the datasheet, page 7 of 69".
_PAGE_LABEL = re.compile(r", page (\d+) of (\d+)$")

#: The label `review_jobs._clause` writes: "checking clause 12 of 60".
_CLAUSE_LABEL = re.compile(r"^checking clause (\d+) of (\d+)$")

#: Job states in which the block is shown.
ACTIVE_STATES = ("queued", "running", "retrying")


class ReviewProgressDetail(BaseModel):
    """What the progress block shows. A figure the row does not hold is null,
    never 0. Ages are seconds on the SERVER's clock, so the browser's clock
    never decides a stall."""

    pages_done: int | None = None
    pages_total: int | None = None
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


def detail(row: dict) -> dict:
    """The block for one job row.

    `pages_done` counts FINISHED pages: the reader reports a page when it
    STARTS it ("page 7 of 69"), so 6 are done. Pages are null outside the
    reading step. `idle_seconds` is the time since the job last moved (its
    progress line or its worker claim); `stale` is job_queue's own rule."""
    match = _PAGE_LABEL.search(row.get("progress_label") or "")
    on_page = int(match.group(1)) if match else None
    total = int(match.group(2)) if match else None
    done = max(0, min(on_page - 1, total)) if total else None
    # Same honest rule as pages: the clause review reports a clause when it
    # STARTS it ("clause 12 of 60"), so 11 are done.
    cm = _CLAUSE_LABEL.match(row.get("progress_label") or "")
    c_on = int(cm.group(1)) if cm else None
    c_total = int(cm.group(2)) if cm else None
    c_done = max(0, min(c_on - 1, c_total)) if c_total else None
    started = job_progress.CLAUSE_STARTED.get(row.get("id") or "")
    c_elapsed = max(0, int(time.time() - started)) if started and c_done is not None else None
    ages = [
        seconds_since(row.get("updated_at")),
        seconds_since(row.get("claimed_at")),
    ]
    ages = [a for a in ages if a is not None]
    claim_age = seconds_since(row.get("claimed_at"))
    return {
        "pages_done": done,
        "pages_total": total if done is not None else None,
        "clauses_done": c_done,
        "clauses_total": c_total if c_done is not None else None,
        "clauses_elapsed_seconds": c_elapsed,
        "elapsed_seconds": seconds_since(row.get("started_at")),
        "idle_seconds": min(ages) if ages else None,
        "stall_amber_seconds": int(settings.review_progress_stall_amber_s),
        "stale": (claim_age is not None and claim_age >= job_queue.CLAIM_STALE_SECONDS),
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
            "SELECT started_at, updated_at, claimed_at FROM jobs WHERE id = ?",
            (job["id"],),
        )
        .fetchone()
    )
    return detail({**job, **(dict(row) if row else {})})
