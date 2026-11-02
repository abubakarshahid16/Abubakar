"""#1525: how many AI answers a review job asked for fresh and how many it reused.

The review audit report (`review_audit`) must never count a stored answer as a
fresh call. The stores that keep no per-run count (`ai_task_runner.run_task`,
`ai_task_runner.reuse_or_ask`, the scope decision cache in `applicability`, the
stored field names in `field_naming`) note each answer here, by step and model.

A ledger exists only while a review job runs with REVIEW_AUDIT_REPORT_ENABLED
on (`recorded`, around `review_jobs.run`). With no ledger open a note does
nothing, so the switch off changes nothing. It holds counts, step names and
model names only, never document text, and is never stored: it ends with the
job. It is a context variable, so a chat answer on another thread is not counted.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .config import settings

_LEDGER: ContextVar[dict | None] = ContextVar("ai_call_ledger", default=None)


@contextmanager
def open_ledger() -> Iterator[None]:
    """Count the notes made inside this block."""
    token = _LEDGER.set({})
    try:
        yield
    finally:
        _LEDGER.reset(token)


def recorded(job):
    """The review job, with a ledger open when the audit report is on."""

    @functools.wraps(job)
    def wrapper(*args, **kwargs):
        if not settings.review_audit_report_enabled:
            return job(*args, **kwargs)
        with open_ledger():
            return job(*args, **kwargs)

    return wrapper


def _note(step: str, model: str | None, field: str, count: int) -> None:
    ledger = _LEDGER.get()
    if ledger is None or not count:
        return
    row = ledger.setdefault((step, model), {"fresh": 0, "reused": 0, "failed": 0})
    row[field] += count


@contextmanager
def asking(step: str, model: str | None, count: int = 1) -> Iterator[None]:
    """A model is asked inside this block: an answer is fresh; a refusal, a timeout or
    any other failure is counted as failed, and still raises."""
    try:
        yield
    except Exception:
        _note(step, model, "failed", count)
        raise
    _note(step, model, "fresh", count)


def fresh(step: str, model: str | None, count: int = 1) -> None:
    """A model was asked: `count` answers called fresh."""
    _note(step, model, "fresh", count)


def reused(step: str, model: str | None, count: int = 1) -> None:
    """`count` stored answers were used and no model was asked. `model` is None
    when the store does not say which model wrote the answer."""
    _note(step, model, "reused", count)


def cache_hit(step: str, model: str | None) -> None:
    """A Claude call answered from the stored answers: reused, and marked so the
    audit can say it was not sent. The key exists only on a row that had one."""
    _note(step, model, "reused", 1)
    ledger = _LEDGER.get()
    if ledger is not None:
        row = ledger[(step, model)]
        row["cache_hits"] = row.get("cache_hits", 0) + 1


def model_of(provider) -> str | None:
    """The model a provider will be asked with, or None when it does not say."""
    return getattr(provider, "requested_model", None)


def snapshot() -> list[dict] | None:
    """One row per (step, model), or None when no ledger is open."""
    ledger = _LEDGER.get()
    if ledger is None:
        return None
    return [
        {"step": step, "model": model, **counts}
        for (step, model), counts in sorted(
            ledger.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        )
    ]
