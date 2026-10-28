"""The settings a review run was queued with, as readable name/value rows (order 309.2).

`config_version` hashes the answer-affecting settings: it tells two runs apart but cannot say WHICH switch differed
("model: not recorded", "switches as the live app holds them today"). This keeps the same settings, by name, beside the
run, written in the SAME transaction that stamps the hash, so the two cannot disagree.

Only names `config.ANSWER_AFFECTING_SETTINGS` already lists, only plain values (a switch, a number, a short word), and
never a name that looks like a key, token, secret, password, path or address: the run record is shown to engineers and
exported, and a setting added to that list later must not put a secret into it by accident.
"""

from __future__ import annotations

import re

from .config import ANSWER_AFFECTING_SETTINGS, settings
from .db import connect

_NEVER = re.compile(
    r"key|token|secret|passw|path|url|host|dir|smtp|email", re.IGNORECASE
)
MAX_VALUE_CHARS = 120


def ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_run_settings (
            review_run_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (review_run_id, name))"""
    )


def snapshot() -> dict[str, str]:
    """{setting name: value as text} of the allowed settings now."""
    out: dict[str, str] = {}
    for name in sorted(ANSWER_AFFECTING_SETTINGS):
        value = getattr(settings, name, None)
        if _NEVER.search(name) or not isinstance(value, (bool, int, float, str)):
            continue
        out[name] = str(value)[:MAX_VALUE_CHARS]
    return out


def record(conn, review_run_id: str) -> None:
    """Write the run's settings on `conn` (inside the caller's transaction)."""
    ensure_schema(conn)
    for name, value in snapshot().items():
        conn.execute(
            "INSERT OR REPLACE INTO review_run_settings (review_run_id, name, value) VALUES (?, ?, ?)",
            (review_run_id, name, value),
        )


def for_run(review_run_id: str) -> dict[str, str]:
    """The stored settings of one run; empty for a run queued before this existed (never a guess)."""
    conn = connect()
    ensure_schema(conn)
    return {
        r["name"]: r["value"]
        for r in conn.execute(
            "SELECT name, value FROM review_run_settings WHERE review_run_id = ? ORDER BY name",
            (review_run_id,),
        )
    }
