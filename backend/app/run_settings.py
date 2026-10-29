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

#: Names that look like a credential, a place or a mail setting. The test applies to TEXT values only: a number or a
#: switch cannot be a key, and `max_output_tokens` is a count, not a credential (cloud-2 on #1466: ten of the 38
#: settings were dropped for having "token" in the name).
_NEVER = re.compile(
    r"key|token|secret|passw|path|url|host|dir|smtp|email", re.IGNORECASE
)
MAX_VALUE_CHARS = 120
NOT_STORED = "settings not stored"
#: Switches that decide what a review says but that `config_version` does not hash (s2, 05:39: the owner turned three
#: on and the hash still read the same). Recorded with the run so "which switches did THIS run have" has an answer;
#: whether they should also change the hash is a separate decision (it would make every readiness check say
#: "config changed" once).
REVIEW_SWITCHES = (
    "rule_auto_use_enabled",
    "tested_cards_decide_enabled",
    "recommendation_queries_enabled",
    "geometry_reader_enabled",
    "datasheet_reader_mode",
    "match_ask_max_per_run",
)


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_run_settings (
            review_run_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (review_run_id, name))"""
    )


def snapshot() -> tuple[dict[str, str], int]:
    """({setting name: value as text} of the allowed settings now, how many named settings were left out)."""
    out: dict[str, str] = {}
    left_out = 0
    for name in sorted({*ANSWER_AFFECTING_SETTINGS, *REVIEW_SWITCHES}):
        value = getattr(settings, name, None)
        plain = isinstance(value, (bool, int, float)) or (
            isinstance(value, str) and not _NEVER.search(name)
        )
        if not plain:
            left_out += 1
            continue
        out[name] = str(value)[:MAX_VALUE_CHARS]
    return out, left_out


def record(conn, review_run_id: str) -> None:
    """Write the run's settings on `conn` (inside the caller's transaction)."""
    ensure_schema(conn)
    stored, left_out = snapshot()
    # The boundary of the list is stored with it: a list read as complete when it is not is a false count.
    stored[NOT_STORED] = (
        f"{left_out} of {len(stored) + left_out} (text values named like a key, path or address, or not plain)"
    )
    for name, value in stored.items():
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
