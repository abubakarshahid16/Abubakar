"""Throughput reporting.

A rate derived from a near-zero denominator is worse than no rate: it looks
authoritative and lands on a dashboard. Every stage that reports throughput
must go through `rate()`, which returns None rather than a fabricated number.
"""

from __future__ import annotations

import time

# Below this, the clock resolution dominates and any rate is noise.
MIN_ELAPSED_S = 0.05


class Timer:
    """Monotonic elapsed-time timer. Not affected by wall-clock changes."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    def seconds(self) -> float:
        """Elapsed seconds at millisecond precision - never rounded to an int."""
        return round(self.elapsed, 3)


def rate(items_this_run: int, elapsed_s: float) -> float | None:
    """Items per second, or None when the number would be meaningless.

    Returns None when nothing was processed in this run (a no-op resume) or
    when the elapsed time is too short to measure. Callers must render None
    as "not measured", never as 0 and never as a placeholder.
    """
    if items_this_run <= 0:
        return None
    if elapsed_s < MIN_ELAPSED_S:
        return None
    return round(items_this_run / elapsed_s, 2)
