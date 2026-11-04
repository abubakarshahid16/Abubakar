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
import functools
import time
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


_report_clause: ContextVar[Callable[[int, int], None] | None] = ContextVar(
    "job_progress_report_clause", default=None
)


@contextlib.contextmanager
def reporting_clauses(callback: Callable[[int, int], None]) -> Iterator[None]:
    """Send `clause(number, total)` calls to `callback` inside this block (#1494)."""
    token = _report_clause.set(callback)
    try:
        yield
    finally:
        _report_clause.reset(token)


#: job id -> wall-clock time its first clause started (#1494). Process-local: a
#: process that does not hold it shows no estimate, never a guessed one.
CLAUSE_STARTED: dict[str, float] = {}


def clause(number: int, total: int) -> None:
    """The AI clause review starts clause `number` of `total` (1-based). Display
    only, like `page`: no callback means nothing happens, and a callback that
    fails is logged and ignored, so a progress line never changes a decision."""
    callback = _report_clause.get()
    if callback is None:
        return
    try:
        callback(number, total)
    except Exception as exc:  # noqa: BLE001 - a progress line never stops a review
        errors.fell_back(
            "job_progress: clause progress not recorded; review goes on", exc, None
        )


_report_requirement: ContextVar[Callable[[int, int], None] | None] = ContextVar(
    "job_progress_report_requirement", default=None
)


@contextlib.contextmanager
def reporting_requirements(callback: Callable[[int, int], None]) -> Iterator[None]:
    """Send `requirement(number, total)` calls to `callback` inside this block."""
    token = _report_requirement.set(callback)
    try:
        yield
    finally:
        _report_requirement.reset(token)


def counting(items):
    """Yield every item of `items` UNCHANGED and in order, telling the callback "starting `number` of `total`" before
    each. DISPLAY ONLY: no callback means a plain pass-through, and a callback that fails is logged and ignored, so
    the comparison's decisions never depend on it."""
    total = len(items)
    callback = _report_requirement.get()
    for number, item in enumerate(items, start=1):
        if callback is not None:
            try:
                callback(number, total)
            except Exception as exc:  # noqa: BLE001 - a progress line never changes a comparison
                callback = None
                errors.fell_back(
                    "job_progress: requirement progress not recorded; comparison goes on",
                    exc,
                    None,
                )
        yield item


#: Which page of how many the reader is on, kept for `logged` (REVIEW_DEBUG).
_where: ContextVar[tuple[int, int] | None] = ContextVar(
    "job_progress_where", default=None
)


def page(number: int, total: int) -> None:
    """The reader is on page `number` of `total` (1-based, in reading order)."""
    _where.set((number, total))
    callback = _report.get()
    if callback is None:
        return
    try:
        callback(number, total)
    except Exception as exc:  # noqa: BLE001 - a progress line never stops a reading
        errors.fell_back(
            "job_progress: page progress not recorded; reading goes on", exc, None
        )


def logged(read: Callable[..., dict]) -> Callable[..., dict]:
    """Decorator for the one-page reader: with `REVIEW_DEBUG` on, print one
    console line when the page is done (page x of y, values found, seconds,
    the model that ran). Off, or if printing fails, the page is read exactly
    as before: this never changes a reading, only watches it."""

    @functools.wraps(read)
    def wrapper(page_text, page_no, model_call, engine, deadline=None):
        from .config import settings

        if not settings.review_debug:
            return read(page_text, page_no, model_call, engine, deadline)
        started = time.monotonic()
        out = read(page_text, page_no, model_call, engine, deadline)
        try:
            from . import review_trace

            review_trace.page_line(
                page_no,
                _where.get(),
                out,
                time.monotonic() - started,
                model_call,
                engine,
            )
        except Exception as exc:  # noqa: BLE001 - a debug line never stops a reading
            errors.fell_back(
                "job_progress: debug line not logged; reading goes on", exc, None
            )
        return out

    return wrapper
