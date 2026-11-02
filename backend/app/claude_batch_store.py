"""#1584: what a Message Batches run keeps in the database it writes, so a crash resumes it and nothing is paid twice.

The request rows, the batches, and every raw answer. Reads and writes that one database only: no socket, no ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .db import add_column_if_missing, connect

#: A request is sent at most this many times by batch: the first send and one re-queue.
MAX_ATTEMPTS = 2
NOT_BILLED = ("errored", "expired", "canceled")
NO_RESULT = "no_result"
#: Written in place of a batch id when the answer came from the answer cache, or from a normal send.
FROM_CACHE = "response_cache"
NORMAL_SEND = "normal_send"
OPEN_STATES = ("open", "canceling")

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS claude_batches (
        id TEXT PRIMARY KEY, job TEXT NOT NULL, api_batch_id TEXT, state TEXT NOT NULL,
        model TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS claude_batch_requests (
        job TEXT NOT NULL, custom_id TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL, batch_row TEXT, reservation_id TEXT, worst_usd REAL, step TEXT, failure TEXT,
        answer TEXT, model TEXT, finish_reason TEXT, api_batch_id TEXT, cache_key TEXT, PRIMARY KEY (job, custom_id))""",
    """CREATE TABLE IF NOT EXISTS claude_batch_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, custom_id TEXT NOT NULL, prompt_version TEXT NOT NULL,
        model TEXT, api_batch_id TEXT, raw_json TEXT NOT NULL, received_at TEXT NOT NULL)""",
)


@dataclass
class Outcome:
    #: custom_id -> {text, model, finish_reason, batch_id}
    answers: dict[str, dict] = field(default_factory=dict)
    #: custom_id -> why, for requests that failed twice and are given up.
    gave_up: dict[str, str] = field(default_factory=dict)
    #: custom_id -> the failure that re-queued it (closed words, never text).
    failures: dict[str, str] = field(default_factory=dict)
    requeued: int = 0
    from_cache: int = 0
    resumed_batches: int = 0
    batch_ids: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    #: A batch had not ended when the wait ran out; the next run polls it.
    waiting: bool = False
    unknown_results: int = 0
    #: custom_ids left out because their worst case did not fit the budget.
    over_budget: list[str] = field(default_factory=list)
    #: The fallback's own counts.
    sent_normal: int = 0
    batches_cancelled: int = 0
    late_results: int = 0


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    with conn:
        for statement in SCHEMA:
            conn.execute(statement)
        add_column_if_missing(conn, "claude_batches", "created_epoch", "REAL")
        add_column_if_missing(conn, "claude_batch_requests", "api_id", "TEXT")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _state(conn, job: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM claude_batch_requests WHERE job = ?", (job,)
    ).fetchall()
    return {r["custom_id"]: dict(r) for r in rows}


def _set(conn, job: str, custom_id: str, **values) -> None:
    columns = ", ".join(f"{name} = ?" for name in values)
    with conn:
        conn.execute(
            f"UPDATE claude_batch_requests SET {columns} WHERE job = ? AND custom_id = ?",
            (*values.values(), job, custom_id),
        )


def _failed(conn, job: str, row: dict, why: str) -> None:
    """Re-queue once, then give up. The failure is a closed word."""
    state = "gave_up" if row["attempts"] >= MAX_ATTEMPTS else "retry"
    _set(conn, job, row["custom_id"], state=state, failure=why)


def _keep_raw(conn, job, custom_id, packet, model, api_batch_id, message) -> None:
    """Every answer as the API sent it, cut off or dropped by the proof too, never replaced: a later reading of the
    answers (a new table shape, a stricter proof) needs no second payment. Local copy only."""
    with conn:
        conn.execute(
            "INSERT INTO claude_batch_answers (job, custom_id, prompt_version, model, api_batch_id, raw_json,"
            " received_at) VALUES (?,?,?,?,?,?,?)",
            (
                job,
                custom_id,
                packet.prompt_version,
                model,
                api_batch_id,
                json.dumps(message, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )


def _answered_elsewhere(
    conn, job: str, custom_id: str, answer, api_batch_id: str
) -> None:
    """An answer that did not come through a batch's own settlement: the cache, or a normal send."""
    with conn:
        conn.execute(
            "INSERT INTO claude_batch_requests (job, custom_id, state, answer, model, finish_reason, api_batch_id)"
            " VALUES (?,?,'answered',?,?,?,?) ON CONFLICT (job, custom_id) DO UPDATE SET state = 'answered',"
            " answer = excluded.answer, model = excluded.model, finish_reason = excluded.finish_reason,"
            " api_batch_id = excluded.api_batch_id",
            (
                job,
                custom_id,
                answer.text,
                answer.model_tag,
                answer.finish_reason,
                api_batch_id,
            ),
        )


def _mark_unconfirmed(conn, job: str) -> None:
    """A batch still 'creating' at the start of a run: the process died inside create."""
    with conn:
        rows = conn.execute(
            "SELECT DISTINCT b.id AS id FROM claude_batches b JOIN claude_batch_requests r ON r.batch_row = b.id"
            " WHERE r.job = ? AND b.state = 'creating'",
            (job,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE claude_batches SET state = 'unconfirmed' WHERE id = ?",
                (row["id"],),
            )
            conn.execute(
                "UPDATE claude_batch_requests SET state = 'unconfirmed' WHERE batch_row = ?",
                (row["id"],),
            )


def _reopen(conn, job: str, usable) -> None:
    """A new run reads again what the last one left unread: requests given up, and answers it could not use (cut off,
    unreadable). Once per run, before anything is collected, so nothing is re-bought inside a run."""
    for custom_id, row in _state(conn, job).items():
        answered = {"text": row["answer"], "finish_reason": row["finish_reason"]}
        bad = row["state"] == "answered" and usable is not None and not usable(answered)
        if row["state"] == "gave_up" or bad:
            _set(
                conn,
                job,
                custom_id,
                state="retry",
                attempts=0,
                failure=None,
                answer=None,
            )


def _finish(conn, job: str, packets, out: Outcome) -> Outcome:
    for custom_id, row in _state(conn, job).items():
        if custom_id not in packets:
            continue
        if row["state"] == "answered":
            out.answers[custom_id] = {
                "text": row["answer"] or "",
                "model": row["model"],
                "finish_reason": row["finish_reason"],
                "batch_id": row["api_batch_id"],
            }
        elif row["state"] == "gave_up":
            out.gave_up[custom_id] = row["failure"] or "unknown"
        elif row["state"] == "unconfirmed":
            out.unconfirmed.append(custom_id)
        if row["failure"]:
            out.failures[custom_id] = row["failure"]
        if row["attempts"] >= MAX_ATTEMPTS:
            out.requeued += 1
    out.batch_ids = sorted(
        {
            r["api_batch_id"]
            for r in conn.execute(
                "SELECT DISTINCT api_batch_id FROM claude_batch_requests WHERE job = ? AND api_batch_id IS NOT NULL"
                " AND api_batch_id NOT IN (?, ?)",
                (job, FROM_CACHE, NORMAL_SEND),
            )
        }
        | {
            r["api_batch_id"]
            for r in conn.execute(
                "SELECT api_batch_id FROM claude_batches WHERE job = ? AND api_batch_id IS NOT NULL",
                (job,),
            )
        }
    )
    return out


def stored_ids(conn, job: str) -> list[str]:
    return sorted(_state(conn, job))


def stored_outcome(conn, job: str, custom_ids: set[str]) -> Outcome:
    """What this copy already holds for a job. Opens nothing and sends nothing."""
    return _finish(conn, job, custom_ids, Outcome())
