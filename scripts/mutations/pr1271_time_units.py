"""#896 (PR 1271): seconds, milliseconds and days convert in the one unit table,
so "480 s" is compared with "at least 8 minutes" instead of `unit_mismatch`."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_896_time_units.py"
_C = APP / "time_units.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1271-01",
        phase=1271,
        description="seconds are no longer a time unit again (480 s against 8 minutes is a mismatch)",
        path=_C,
        anchor='    ("s sec secs second seconds", 1.0 / 3600.0),\n',
        replacement="",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1271-02",
        phase=1271,
        description="a millisecond is read as a second (250 ms limit met by 0.3 s)",
        path=_C,
        anchor='    ("ms msec millisecond milliseconds", 1.0 / 3600000.0),\n',
        replacement='    ("ms msec millisecond milliseconds", 1.0 / 3600.0),\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1271-03",
        phase=1271,
        description="a day is read as an hour",
        path=_C,
        anchor='    ("day days", 24.0),\n',
        replacement='    ("day days", 1.0),\n',
        target=_T,
        tags=("honesty",),
    ),
)
