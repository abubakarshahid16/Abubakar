"""Per-model latency and error counts, stored per review run (#503).

Every local model call made while a review job runs on the worker notes its model,
its seconds and, on a failure, the KIND of the error into the running review's bucket
(`reasoning_provider.OllamaProvider.reason`). When the job ends the bucket is stored,
one row per model per run with the date: calls, errors, seconds total and longest,
the error kinds with their counts. COUNTS AND SECONDS ONLY: never a prompt, an answer,
a page or an exception message.

Outside a review job nothing is noted (no bucket), so chat and ingestion are untouched.
`gold_score` is empty on purpose: the gold-set score of a model is a measurement s2
makes and attaches; the issue's "kept only if the score rises" is decided from it.
Storing never raises into the review: losing a sample is not worth failing one.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from .db import connect

log = logging.getLogger(__name__)

_BUCKET: ContextVar[dict | None] = ContextVar("model_metrics_bucket", default=None)


@contextmanager
def collect() -> Iterator[dict]:
    """Within the block, local model calls on this thread are noted into the yielded bucket."""
    bucket: dict[str, dict] = {}
    token = _BUCKET.set(bucket)
    try:
        yield bucket
    finally:
        _BUCKET.reset(token)


def note(model: str, seconds: float, error: str | None = None) -> None:
    """One model call: its seconds, and the error kind when it failed. No-op outside `collect`."""
    bucket = _BUCKET.get()
    if bucket is None:
        return
    row = bucket.setdefault(
        str(model),
        {"calls": 0, "errors": 0, "seconds": 0.0, "longest": 0.0, "kinds": {}},
    )
    row["calls"] += 1
    row["seconds"] += float(seconds)
    row["longest"] = max(row["longest"], float(seconds))
    if error:
        row["errors"] += 1
        row["kinds"][error] = row["kinds"].get(error, 0) + 1


def failed(model: str, started: float, error: BaseException) -> None:
    """A model call that raised: the seconds since `started` and the error's TYPE (never its message)."""
    note(model, time.time() - started, type(error).__name__)


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS model_call_metrics (
                review_run_id TEXT NOT NULL, model TEXT NOT NULL, day TEXT NOT NULL,
                calls INTEGER NOT NULL, errors INTEGER NOT NULL,
                seconds_total REAL NOT NULL, seconds_longest REAL NOT NULL,
                error_kinds TEXT NOT NULL, gold_score REAL, created_at TEXT NOT NULL,
                PRIMARY KEY (review_run_id, model))"""
        )


def store(review_run_id: str | None, bucket: dict) -> None:
    """The bucket as rows of the run. Never raises."""
    if not review_run_id or not bucket:
        return
    try:
        ensure_schema()
        now = datetime.now(UTC)
        with connect() as conn:
            for model, row in sorted(bucket.items()):
                conn.execute(
                    "INSERT OR REPLACE INTO model_call_metrics (review_run_id, model, day, calls,"
                    " errors, seconds_total, seconds_longest, error_kinds, gold_score, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (
                        review_run_id,
                        model,
                        now.date().isoformat(),
                        row["calls"],
                        row["errors"],
                        round(row["seconds"], 3),
                        round(row["longest"], 3),
                        json.dumps(row["kinds"], sort_keys=True),
                        now.isoformat(timespec="seconds"),
                    ),
                )
    except Exception as exc:  # noqa: BLE001 - a lost sample must not fail the review
        log.warning("model metrics were not stored (%s)", type(exc).__name__)


def store_for_job(job_id: str, bucket: dict) -> None:
    """`store`, for the run a job belongs to."""
    try:
        row = (
            connect()
            .execute("SELECT review_run_id FROM jobs WHERE id = ?", (job_id,))
            .fetchone()
        )
    except Exception as exc:  # noqa: BLE001 - see `store`
        log.warning("model metrics: no run for the job (%s)", type(exc).__name__)
        return
    store(row["review_run_id"] if row else None, bucket)


def for_run(review_run_id: str) -> list[dict]:
    """The stored rows of one run, by model."""
    ensure_schema()
    rows = connect().execute(
        "SELECT * FROM model_call_metrics WHERE review_run_id = ? ORDER BY model",
        (review_run_id,),
    )
    return [{**dict(r), "error_kinds": json.loads(r["error_kinds"])} for r in rows]
