"""The time rows of the one unit table (`claims._UNIT_TABLE`).

Hours are the base, as they always were here. Every factor is exact by
definition, so "480 s" and "8 minutes" are the same time. Seconds,
milliseconds and days were missing until #896: a limit in minutes was never
compared with a value in seconds (it came back "not the same quantity")."""

from __future__ import annotations

_SPELLINGS: tuple[tuple[str, float], ...] = (
    ("h hr hrs hour hours", 1.0),
    ("min mins minute minutes", 1.0 / 60.0),
    ("s sec secs second seconds", 1.0 / 3600.0),
    ("ms msec millisecond milliseconds", 1.0 / 3600000.0),
    ("day days", 24.0),
)

#: spelling -> (dimension, base unit, factor to the base), as `_UNIT_TABLE` rows.
TABLE: dict[str, tuple[str, str, float]] = {
    spelling: ("time", "h", factor)
    for spellings, factor in _SPELLINGS
    for spelling in spellings.split()
}
