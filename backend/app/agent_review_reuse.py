"""Stored first-reader answers (order 13, point E: steady results). Off unless `agent_review_reuse_answers_enabled`.

WHAT IS REUSED. The reader's RAW answer to one request, when an earlier finished run of the AI reviewer already got a complete,
readable answer to a request that is byte-identical: same system text, same messages (the paper's pages, the held rule texts, the
items), same model, same output limit, same prompt version. Nothing else: no verdict, no line, no class. The quote check, the guards,
the second readers and the class rules run again on a reused answer, exactly as on a new one.

WHAT IT HIDES (said in the PR and the trace): the first run's sampling noise stays, and a wrong first answer stays until a run asks
for fresh answers (`fresh`: the start route and `scripts/trial_on_copy.py --fresh`; the fresh answers replace the stored ones).

NEVER STORED: an answer cut off at its limit, unreadable, refused, or from a run that was halted (a cap, a refusal, a cancel). An
answer is held in memory while its run works and written only when the run ends without a stop.

WHERE: the app database, table `agent_review_answer` (local only: it holds AI answer text, which quotes the paper and the rule books;
never in a log, an issue, a PR or CI; the database backup covers it). The spend ledger and `claude_spend` are not touched: a reused
answer makes no call and books USD 0, and this module never reaches the transport.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

KEY_VERSION = "reuse-1"
#: the key of the note a reused answer carries (stripped before anything else reads it)
NOTE = "_reused_answer"

_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS agent_review_answer (
        request_key TEXT PRIMARY KEY,
        prompt_version TEXT NOT NULL,
        model TEXT NOT NULL,
        max_tokens INTEGER NOT NULL,
        answered_model TEXT,
        answer_json TEXT NOT NULL,
        from_run_id TEXT NOT NULL,
        submittal_document_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS agent_review_answer_run (
        run_id TEXT PRIMARY KEY,
        fresh INTEGER NOT NULL DEFAULT 0
    )""",
)


def enabled() -> bool:
    from .config import settings

    return bool(settings.agent_review_reuse_answers_enabled)


def ensure_tables(conn: sqlite3.Connection) -> None:
    for statement in _STATEMENTS:
        conn.execute(statement)


def record_fresh(conn: sqlite3.Connection, run_id: str, fresh: bool) -> None:
    """The start route's `fresh` option for one run. Nothing is written when the switch is off or `fresh` is not asked."""
    if not (enabled() and fresh):
        return
    ensure_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO agent_review_answer_run (run_id, fresh) VALUES (?, 1)",
        (run_id,),
    )


def is_fresh(conn: sqlite3.Connection, run_id: str) -> bool:
    try:
        row = conn.execute(
            "SELECT fresh FROM agent_review_answer_run WHERE run_id = ?", (run_id,)
        ).fetchone()
    except sqlite3.OperationalError:  # the table was never made: no run asked for fresh
        return False
    return bool(row and row[0])


def request_key(
    model: str, parts: Mapping, max_tokens: int, prompt_version: str
) -> str:
    """The key: a SHA-256 of everything the app puts in the request, plus the model, the limit and the prompt version. (The spend
    ledger's `prompt_sha256` hashes the finished body, which needs the key and the open gate to build; this is built before the
    transport is reached and covers the same fields. The two constants the transport adds, whether a temperature is sent and
    whether the model thinks by default, are in it too.)"""
    from . import claude_spend
    from .reader_api import _rejects_temperature

    body = {
        "v": KEY_VERSION,
        "prompt_version": prompt_version,
        "model": model,
        "max_tokens": int(max_tokens),
        "system": parts.get("system"),
        "messages": parts.get("messages"),
        "temperature_sent": not _rejects_temperature(model),
        "thinks_by_default": bool(claude_spend.thinks_by_default(model)),
    }
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def complete(answer: Any) -> bool:
    """A complete reply: a dict that ended its turn (not at the limit, not a refusal) and holds content."""
    return (
        isinstance(answer, dict)
        and answer.get("stop_reason") == "end_turn"
        and isinstance(answer.get("content"), list)
        and bool(answer["content"])
    )


class AnswerStore:
    """One run's view of the stored answers. `lookup` reads (never when `fresh`), `remember` keeps an answer in memory, `commit`
    writes what was kept (called only by a run that ended without a stop)."""

    def __init__(
        self,
        run_id: str,
        submittal: str,
        prompt_version: str,
        *,
        fresh: bool = False,
        connect: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self.run_id, self.submittal, self.prompt_version = (
            run_id,
            submittal,
            prompt_version,
        )
        self.fresh = bool(fresh)
        self._connect = connect
        self._pending: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self.reused = 0
        self.stored = 0

    def _conn(self) -> sqlite3.Connection:
        if self._connect is not None:
            return self._connect()
        from .db import connect

        return connect()

    def key(self, model: str, parts: Mapping, max_tokens: int) -> str:
        return request_key(model, parts, max_tokens, self.prompt_version)

    def lookup(self, key: str) -> dict | None:
        """{"answer", "run_id", "date"} for a stored complete answer to exactly this request, else None. A fresh run never reads."""
        if self.fresh:
            return None
        try:
            row = (
                self._conn()
                .execute(
                    "SELECT answer_json, from_run_id, created_at, prompt_version FROM agent_review_answer WHERE request_key = ?",
                    (key,),
                )
                .fetchone()
            )
        except sqlite3.Error as exc:  # no table yet, or a busy database: a miss, never a failure of the run
            log.warning("agent review reuse: lookup failed (%s)", type(exc).__name__)
            return None
        if row is None or row[3] != self.prompt_version:
            return None
        try:
            answer = json.loads(row[0])
        except ValueError:
            return None
        if not complete(answer):
            return None
        with self._lock:
            self.reused += 1
        return {"answer": answer, "run_id": row[1], "date": str(row[2])[:10]}

    def forget(self, key: str) -> None:
        """Drop a stored answer the caller found unusable (never loops: the next ask is a real call)."""
        try:
            self._conn().execute(
                "DELETE FROM agent_review_answer WHERE request_key = ?", (key,)
            )
        except sqlite3.Error as exc:
            log.warning("agent review reuse: forget failed (%s)", type(exc).__name__)

    def remember(self, key: str, model: str, max_tokens: int, answer: Mapping) -> None:
        """Keep a NEW complete answer until the run ends. The caller has checked it is readable."""
        if not complete(answer):
            return
        with self._lock:
            self._pending[key] = (model, int(max_tokens), dict(answer))

    def commit(self) -> int:
        """Write the kept answers (INSERT OR REPLACE: a fresh run replaces the stored ones). Returns how many."""
        with self._lock:
            pending, self._pending = self._pending, {}
        if not pending:
            return 0
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            conn = self._conn()
            ensure_tables(conn)
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO agent_review_answer (request_key, prompt_version, model, max_tokens, answered_model,"
                    " answer_json, from_run_id, submittal_document_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    [
                        (k, self.prompt_version, m, n, str(a.get("model") or ""),
                         json.dumps(a, ensure_ascii=False, default=str), self.run_id, self.submittal, now)
                        for k, (m, n, a) in pending.items()
                    ],
                )  # fmt: skip
        except sqlite3.Error as exc:
            log.warning("agent review reuse: commit failed (%s)", type(exc).__name__)
            return 0
        self.stored = len(pending)
        return self.stored


def sentence(note: Mapping) -> str:
    """The plain words the trace and the Evidence sheet carry."""
    return f"reused answer from run {note.get('run_id')} of {note.get('date')}"
