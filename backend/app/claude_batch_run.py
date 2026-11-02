"""A Message Batches run that survives a crash and never pays twice (#1584).

`ClaudeProvider.reason_batch` holds its state in memory: a crash while it waits loses the batch id, and the
next run sends and pays again. This module keeps that state in the database the run writes (a disposable copy,
`scripts/compile_standards.py`): the batch id, and per request its reservation, state and answer.

ONE LANE. Bodies come from `ClaudeProvider._request`, answers go through `ClaudeProvider._answered` (ledger,
response cache), bytes through `reader_transport.batch_*` or a test's fake. Nothing here opens a socket.

THE LEDGER. Every request's worst case is reserved in one locked step (`claude_spend.reserve_all`, which also
asks the approved list) BEFORE the batch is created, and the reservation id is stored. So after a crash the
reservation is still counted at its worst case and a resumed run settles the SAME reservation.

  * succeeded: settled to its usage at the batch price, keyed by custom_id, results in any order.
  * errored, expired, canceled: not billed, so released; re-queued once, then listed and counted.
  * no result row at all: charged its worst case (unknown is never free), re-queued once.
  * a crash, or a failed poll, while waiting: nothing is settled; the next run polls the same batch.
  * a crash or a timeout inside create: the API may hold the batch and its id is unknown. The requests are
    "unconfirmed", stay charged, and are NOT sent again unless the operator says so.

One known overcount: a crash between a settlement and the commit after it settles that reservation twice when
the batch is read again. That errs toward spent, never toward unspent.

Stored: answers, in the disposable copy only. Logged: nothing here; the ledger holds counts and digests.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import claude_spend
from .reasoning_provider import (
    ClaudeProvider,
    Packet,
    ProviderRefused,
    _cache_version,
    _unbilled,
    _valid_for,
)

#: A request is sent at most this many times: the first send and one re-queue.
MAX_ATTEMPTS = 2
#: The instruction `ClaudeProvider._request` writes around a packet's JSON schema, in characters.
_SCHEMA_WRAPPER_CHARS = 120
NOT_BILLED = ("errored", "expired", "canceled")
NO_RESULT = "no_result"
#: Written in place of a batch id when the answer came from the response cache.
FROM_CACHE = "response_cache"

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


def ensure_schema(conn) -> None:
    with conn:
        for statement in SCHEMA:
            conn.execute(statement)


def worst_usd(model: str, packet: Packet) -> float:
    """The most this request can cost at the batch price; needs no key, so an estimate can run with the lane shut."""
    chars = len(packet.system) + len(packet.prompt)
    if packet.json_schema is not None:
        chars += _SCHEMA_WRAPPER_CHARS + len(
            json.dumps(packet.json_schema, separators=(",", ":"))
        )
    return claude_spend.worst_case_usd(model, chars, packet.num_predict, batch=True)


def _fitting(worsts: list[tuple[str, float]], room: float) -> int:
    """How many requests, from the first, fit `room` at their worst case together."""
    total, count = 0.0, 0
    for _step, worst in worsts:
        total += worst
        if total > room:
            break
        count += 1
    return count


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


def _reservation(row: dict, model: str) -> claude_spend.Reservation:
    return claude_spend.Reservation(
        row["reservation_id"],
        row["step"],
        model,
        float(row["worst_usd"]),
        "",
        time.time(),
        True,
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


def _from_cache(conn, job: str, custom_id: str, hit) -> None:
    with conn:
        conn.execute(
            "INSERT INTO claude_batch_requests (job, custom_id, state, answer, model, finish_reason, api_batch_id)"
            " VALUES (?,?,'answered',?,?,?,?) ON CONFLICT (job, custom_id) DO UPDATE SET state = 'answered',"
            " answer = excluded.answer, model = excluded.model, finish_reason = excluded.finish_reason,"
            " api_batch_id = excluded.api_batch_id",
            (job, custom_id, hit.text, hit.model_tag, hit.finish_reason, FROM_CACHE),
        )


def _hold(
    conn, job: str, model: str, sending: list[str], held: list, keys: list[str]
) -> str:
    """Written BEFORE the send: a crash from here on still knows every reservation."""
    batch_row = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO claude_batches (id, job, state, model, created_at) VALUES (?,?,'creating',?,?)",
            (batch_row, job, model, _now()),
        )
        for custom_id, reservation, key in zip(sending, held, keys, strict=True):
            conn.execute(
                "INSERT INTO claude_batch_requests (job, custom_id, attempts, state, batch_row, reservation_id,"
                " worst_usd, step, cache_key) VALUES (?,?,1,'held',?,?,?,?,?) ON CONFLICT (job, custom_id) DO UPDATE SET"
                " attempts = attempts + 1, state = 'held', batch_row = excluded.batch_row,"
                " reservation_id = excluded.reservation_id, worst_usd = excluded.worst_usd, step = excluded.step,"
                " cache_key = excluded.cache_key",
                (
                    job,
                    custom_id,
                    batch_row,
                    reservation.id,
                    reservation.worst_usd,
                    reservation.step,
                    key,
                ),
            )
    return batch_row


def _create_failed(conn, batch_row: str, held: list, exc: Exception) -> None:
    """Charged unless it provably cost nothing. A create that may have worked is "unconfirmed", never re-sent alone."""
    for reservation in held:
        claude_spend.settle_failure(reservation, exc, unbilled=_unbilled)
    state = "not_sent" if _unbilled(exc) else "unconfirmed"
    with conn:
        conn.execute(
            "UPDATE claude_batches SET state = ? WHERE id = ?", (state, batch_row)
        )
        conn.execute(
            "UPDATE claude_batch_requests SET state = ?, attempts = attempts - ? WHERE batch_row = ?",
            (state, 1 if _unbilled(exc) else 0, batch_row),
        )


def _submit(
    conn,
    provider: ClaudeProvider,
    job,
    packets,
    todo,
    client,
    room,
    out: Outcome,
    cache_system: bool,
) -> str | None:
    """Send `todo` as one batch and store its id. Returns the local batch row, or None when all were cached."""
    model = provider.requested_model
    to_send, worsts, sending, keys, request = [], [], [], [], None
    for custom_id in todo:
        packet = packets[custom_id]
        step = provider._step or packet.step
        request, body, _prompt = provider._request(packet)
        if not cache_system:  # a job that would only ever pay the dearer write
            body["system"] = [
                {k: v for k, v in block.items() if k != "cache_control"}
                for block in body.get("system", [])
            ]
        stored, key = claude_spend.answer_on_file(
            step,
            body,
            version=_cache_version(packet),
            valid=_valid_for(packet),
            prompt_sha256=packet.sha256,
        )
        if stored is not None:
            _from_cache(
                conn, job, custom_id, provider._response(stored, packet, 0.0, 0.0)
            )
            _keep_raw(
                conn, job, custom_id, packet, stored.get("model"), FROM_CACHE, stored
            )
            out.from_cache += 1
            continue
        keys.append(key)
        to_send.append({"custom_id": custom_id, "params": body})
        worsts.append((step, worst_usd(model, packet)))
        sending.append(custom_id)
    if not to_send:
        return None
    if (
        room is not None
    ):  # the first requests that fit go; the rest are named, never sent
        fits = _fitting(worsts, room())
        out.over_budget += sending[fits:]
        to_send, worsts, sending, keys = (
            to_send[:fits],
            worsts[:fits],
            sending[:fits],
            keys[:fits],
        )
    if not to_send:
        return None
    held = claude_spend.reserve_all(worsts, model=model, batch=True)
    batch_row = _hold(conn, job, model, sending, held, keys)
    try:
        batch = client.batch_create(
            request["url"], headers=request["headers"], requests=to_send
        )
    except Exception as exc:
        _create_failed(conn, batch_row, held, exc)
        raise ProviderRefused(
            f"claude: the batch was not created: {claude_spend.failure_word(exc)}"
        ) from exc
    with conn:
        conn.execute(
            "UPDATE claude_batches SET api_batch_id = ?, state = 'open' WHERE id = ?",
            (str(batch.get("id")), batch_row),
        )
        conn.execute(
            "UPDATE claude_batch_requests SET api_batch_id = ? WHERE batch_row = ?",
            (str(batch.get("id")), batch_row),
        )
    return batch_row


def _take_result(
    conn, provider, job, packets, held: dict, result: dict, wall: float
) -> None:
    """One result row, whichever position it came in."""
    model = provider.requested_model
    custom_id = held["custom_id"]
    kind = str(result.get("type"))
    reservation = _reservation(held, model)
    if kind == "succeeded":
        packet = packets[custom_id]
        message = result.get("message") or {}
        _keep_raw(
            conn,
            job,
            custom_id,
            packet,
            message.get("model"),
            held["api_batch_id"],
            message,
        )
        answer = provider._answered(
            result.get("message"),
            packet,
            held["cache_key"],
            held["step"],
            wall,
            batch=True,
            reservation=reservation,
        )
        _set(
            conn,
            job,
            custom_id,
            state="answered",
            answer=answer.text,
            model=answer.model_tag,
            finish_reason=answer.finish_reason,
        )
    elif kind in NOT_BILLED:
        claude_spend.release(reservation, f"unbilled:batch_{kind}")
        _failed(conn, job, held, kind)
    else:
        claude_spend.settle(
            reservation, usage=None, finish_reason=f"failed:batch_{NO_RESULT}"
        )
        _failed(conn, job, held, NO_RESULT)


def _collect(
    conn,
    provider,
    job,
    packets,
    batch_row,
    client,
    *,
    poll_seconds,
    deadline,
    sleep,
    out: Outcome,
) -> bool:
    """Wait for one batch and take its results. False when the wait ran out (nothing settled, nothing lost)."""
    found = conn.execute(
        "SELECT api_batch_id FROM claude_batches WHERE id = ?", (batch_row,)
    ).fetchone()
    api_id = found["api_batch_id"]
    request, _body, _prompt = provider._request(next(iter(packets.values())))
    url, headers = request["url"], request["headers"]
    started = time.time()
    batch = client.batch_retrieve(url, api_id, headers=headers)
    while batch.get("processing_status") != "ended":
        if time.time() >= deadline:
            return False
        sleep(poll_seconds)
        batch = client.batch_retrieve(url, api_id, headers=headers)
    rows = _state(conn, job)
    for row in client.batch_results(str(batch.get("results_url")), headers=headers):
        custom_id = str(row.get("custom_id"))
        held = rows.get(custom_id)
        if (
            held is None
            or held["state"] != "held"
            or held["batch_row"] != batch_row
            or custom_id not in packets
        ):
            out.unknown_results += 1
            continue
        _take_result(
            conn,
            provider,
            job,
            packets,
            held,
            row.get("result") or {},
            time.time() - started,
        )
    for held in _state(conn, job).values():  # a request the results never named
        if held["state"] == "held" and held["batch_row"] == batch_row:
            _take_result(conn, provider, job, packets, held, {}, time.time() - started)
    with conn:
        conn.execute(
            "UPDATE claude_batches SET state = 'ended' WHERE id = ?", (batch_row,)
        )
    return True


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


def _open_batches(conn, job: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM claude_batches WHERE job = ? AND state = 'open' ORDER BY created_at, id",
        (job,),
    ).fetchall()
    return [r["id"] for r in rows]


def _mark_unconfirmed(conn, job: str) -> None:
    """A batch still 'creating' at the start of a run: the process died inside create."""
    with conn:
        rows = conn.execute(
            "SELECT id FROM claude_batches WHERE job = ? AND state = 'creating'", (job,)
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
                "SELECT api_batch_id FROM claude_batches WHERE job = ? AND api_batch_id IS NOT NULL",
                (job,),
            )
        }
    )
    return out


def run(
    conn,
    provider: ClaudeProvider,
    job: str,
    packets: dict[str, Packet],
    *,
    client=None,
    room=None,
    usable=None,
    poll_seconds: float = 60.0,
    max_wait_s: float = 86400.0,
    sleep=time.sleep,
    resend_unconfirmed: bool = False,
    cache_system: bool = True,
) -> Outcome:
    """Answer every packet, or say which were not. Open batches of this job are read first, so a run after a crash
    polls what it already paid for; only then is anything new sent. `room()` is the USD still free: what does not fit is left out."""
    ensure_schema(conn)
    if client is None:
        from . import reader_transport

        if not reader_transport.available():
            raise ProviderRefused(
                "claude: egress is disabled (STANDARDS_READER_ENABLED / STANDARDS_READER_ALLOW_PUBLIC_EGRESS)"
            )
        client = reader_transport
    out = Outcome()
    _mark_unconfirmed(conn, job)
    _reopen(conn, job, usable)
    waits = {
        "poll_seconds": poll_seconds,
        "deadline": time.time() + max_wait_s,
        "sleep": sleep,
        "out": out,
    }
    for batch_row in _open_batches(conn, job):
        out.resumed_batches += 1
        if not _collect(conn, provider, job, packets, batch_row, client, **waits):
            out.waiting = True
            return _finish(conn, job, packets, out)
    again = ("retry", "not_sent") + (("unconfirmed",) if resend_unconfirmed else ())
    while True:
        rows = _state(conn, job)
        todo = [
            c
            for c in packets
            if (c not in rows or rows[c]["state"] in again) and c not in out.over_budget
        ]
        if not todo:
            return _finish(conn, job, packets, out)
        batch_row = _submit(
            conn, provider, job, packets, todo, client, room, out, cache_system
        )
        if batch_row is not None and not _collect(
            conn, provider, job, packets, batch_row, client, **waits
        ):
            out.waiting = True
            return _finish(conn, job, packets, out)
