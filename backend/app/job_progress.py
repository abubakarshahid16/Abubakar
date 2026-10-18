"""Order 95 piece 3b: "page x of y" while a review reads its datasheet.

A review job reports progress in three named steps (`review_jobs.STEPS`), and
the first one - reading the datasheet - is the slow one: the AI page reader
can take minutes per page. This module lets the page loop say which page it
is on without the reader knowing about jobs: the job sets a callback for the
duration of its reading step, and the reader calls `page(done, total)`.

DISPLAY ONLY. No callback set (ingestion, a re-read route, a test) means
nothing happens; a callback that fails is logged and ignored, so a progress
line can never change or stop a reading.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextvars import ContextVar

from . import errors

_report: ContextVar[Callable[[int, int], None] | None] = ContextVar(
    "job_progress_report", default=None
)


@contextlib.contextmanager
def reporting(callback: Callable[[int, int], None]) -> Iterator[None]:
    """Send `page(done, total)` calls to `callback` inside this block."""
    token = _report.set(callback)
    try:
        yield
    finally:
        _report.reset(token)


def page(number: int, total: int) -> None:
    """The reader is on page `number` of `total` (1-based, in reading order)."""
    callback = _report.get()
    if callback is None:
        return
    try:
        callback(number, total)
    except Exception as exc:  # noqa: BLE001 - a progress line never stops a reading
        errors.fell_back(
            "job_progress: page progress not recorded; reading goes on", exc, None
        )
