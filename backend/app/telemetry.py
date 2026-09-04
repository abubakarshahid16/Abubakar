"""Measured rates and latencies, persisted.

The dashboard is not allowed to show a placeholder, which means every number
on it has to come from somewhere real. An in-memory counter would have reset
on every restart and left "processing speed" blank on a screen a client is
looking at, so stage timings are written to a table as they happen and the
dashboard aggregates them.

Two rules carried over from the rate bug earlier in this build:

  * a rate is never computed from an interval too short to measure - see
    rates.rate(), which returns None below 50ms rather than a number like
    1021658887.25 pages/sec
  * a stage that has never run reports None, not zero. Zero is a measurement;
    "no measurement" is not.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .db import connect
from .rates import rate

#: Kept per stage. Enough to be a stable median, small enough that the table
#: never becomes something that needs managing.
KEEP_PER_STAGE = 2000

EXTRACT = "extract"
CHUNK = "chunk"
KEYWORD_INDEX = "keyword_index"
EMBED = "embed"
RETRIEVAL = "retrieval"

#: The unit each stage is measured in, so the dashboard can label it without
#: hardcoding a mapping that could drift out of step with what is recorded.
UNITS = {
    EXTRACT: "pages/s",
    CHUNK: "chunks/s",
    KEYWORD_INDEX: "chunks/s",
    EMBED: "chunks/s",
    RETRIEVAL: "ms",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def record(stage: str, items: int, seconds: float, document_id: str | None = None) -> None:
    """Record one completed stage run. Never raises into the caller.

    A failed measurement must not fail the work being measured - losing a
    dashboard sample is not worth failing an ingestion over.
    """
    try:
        computed = rate(items, seconds)
        conn = connect()
        with conn:
            conn.execute(
                """INSERT INTO stage_runs (stage, document_id, items, seconds, rate, at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (stage, document_id, items, round(seconds, 6), computed, _now()),
            )
            # Trim in the same transaction so the table cannot grow unbounded
            # between two writes.
            conn.execute(
                """DELETE FROM stage_runs WHERE stage = ? AND id NOT IN (
                       SELECT id FROM stage_runs WHERE stage = ?
                       ORDER BY id DESC LIMIT ?
                   )""",
                (stage, stage, KEEP_PER_STAGE),
            )
    except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
        pass


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 2)


def throughput() -> dict[str, dict | None]:
    """Median and best measured rate per processing stage.

    Median rather than mean: a single batch that ran while the laptop was
    thermally throttled should not become the number on the screen, and nor
    should the fastest one.
    """
    out: dict[str, dict | None] = {}
    conn = connect()
    for stage in (EXTRACT, CHUNK, KEYWORD_INDEX, EMBED):
        rows = conn.execute(
            """SELECT rate, items, seconds FROM stage_runs
               WHERE stage = ? AND rate IS NOT NULL
               ORDER BY id DESC LIMIT ?""",
            (stage, KEEP_PER_STAGE),
        ).fetchall()
        rates = [r["rate"] for r in rows]
        if not rates:
            # never run, or never run long enough to be measurable
            out[stage] = None
            continue
        out[stage] = {
            "unit": UNITS[stage],
            "samples": len(rates),
            "median": round(statistics.median(rates), 2),
            "best": round(max(rates), 2),
            "items_total": sum(r["items"] for r in rows),
            "seconds_total": round(sum(r["seconds"] for r in rows), 2),
        }
    return out


def retrieval_latency() -> dict | None:
    """Answer latency in milliseconds, from real questions actually asked."""
    rows = connect().execute(
        """SELECT seconds FROM stage_runs WHERE stage = ?
           ORDER BY id DESC LIMIT ?""",
        (RETRIEVAL, KEEP_PER_STAGE),
    ).fetchall()
    ms = [r["seconds"] * 1000 for r in rows]
    if not ms:
        return None
    return {
        "unit": "ms",
        "samples": len(ms),
        "p50": _percentile(ms, 0.5),
        "p95": _percentile(ms, 0.95),
        "worst": round(max(ms), 2),
    }
