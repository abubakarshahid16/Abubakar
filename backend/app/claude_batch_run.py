"""Message Batches for many standards at once: survives a crash, never pays twice, can fall back to normal sends (#1584).

`ClaudeProvider.reason_batch` holds its state in memory: a crash while it waits loses the batch id, and the
next run sends and pays again. This module keeps that state in the database the run writes (a disposable copy,
`scripts/compile_standards.py`): the batch id, and per request its reservation, state and answer.

ONE LANE. Bodies come from `ClaudeProvider._request`, answers go through `ClaudeProvider._answered` (ledger,
answer cache), bytes through `reader_transport.batch_*` or a test's fake. Nothing here opens a socket.

ONE BATCH ACROSS STANDARDS. `run_many` takes several jobs, one per standard, and sends them together. Each request
reserves on its own standard's step, so the per-standard cap holds inside one batch. Only the API's own size limits
split it (`MAX_BATCH_REQUESTS`, `MAX_BATCH_BYTES`).

THE LEDGER. Every request's worst case is reserved BEFORE the batch is created, and the reservation id is stored.
So after a crash the reservation is still counted at its worst case and a resumed run settles the SAME one.

  * succeeded: settled to its usage at the batch price, keyed by custom_id, results in any order.
  * errored, expired, canceled: not billed, so released; re-queued once, then listed and counted.
  * no result row at all: charged its worst case (unknown is never free), re-queued once; if the row turns up on a
    later read it is used, and not charged again.
  * a crash, or a failed poll, while waiting: nothing is settled; the next run polls the same batch.
  * a crash or a timeout inside create: the API may hold the batch and its id is unknown. The requests are
    "unconfirmed", stay charged, and are NOT sent again unless the operator says so.

THE FALLBACK (`fallback_after_s`, default off). A batch older than that is cancelled. NOTHING IS SENT UNTIL THE BATCH HAS
ENDED, so no request can be paid twice: a cancel that fails, or one not finished within `CANCEL_WAIT_S`, leaves the run
"waiting". What the batch had finished is kept at the batch price; only what it did not is sent, one by one through
`ClaudeProvider.reason`: same model, same prompt version, same answer cache, at the normal price. Before each send its
worst case at that price must fit what is free (`room`). What does not fit is not sent and is named.

One known overcount: a crash between a settlement and the commit after it settles that reservation twice when
the batch is read again. That errs toward spent, never toward unspent.

Stored: answers, in the disposable copy only. Logged: nothing here; the ledger holds counts and digests.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass

from . import claude_approved, claude_spend, reader_api
from .claude_batch_store import (
    FROM_CACHE,
    MAX_ATTEMPTS,
    NO_RESULT,
    NORMAL_SEND,
    NOT_BILLED,
    OPEN_STATES,
    Outcome,
    _answered_elsewhere,
    _failed,
    _finish,
    _keep_raw,
    _mark_unconfirmed,
    _now,
    _reopen,
    _set,
    _state,
    ensure_schema,
    stored_ids,
    stored_outcome,
)
from .reasoning_provider import (
    ClaudeProvider,
    Packet,
    ProviderRefused,
    _cache_version,
    _unbilled,
    _valid_for,
)

log = logging.getLogger(__name__)

#: Names other modules read from here.
__all__ = [
    "MAX_ATTEMPTS",
    "stored_ids",
    "stored_outcome",
]

#: The Batch API's own limits are 100,000 requests and 256 MB. The bytes here stay under that for the JSON around them.
MAX_BATCH_REQUESTS = 100_000
MAX_BATCH_BYTES = 200 * 1024 * 1024
#: How long a cancelled batch may take to end before the run stops and says "waiting". Seconds.
CANCEL_WAIT_S = 600.0
#: The instruction `ClaudeProvider._request` writes around a packet's JSON schema, in characters.
_SCHEMA_WRAPPER_CHARS = 120


@dataclass
class _Run:
    """What one call of `run_many` holds on to."""

    conn: object
    provider: ClaudeProvider
    work: dict[str, dict[str, Packet]]
    client: object
    room: object
    declared: dict[str, set[str]]
    cache_system: dict[str, bool]
    out: dict[str, Outcome]
    poll_seconds: float
    sleep: object
    clock: object
    deadline: float
    fallback_after_s: float | None

    def carrying(self, job: str):
        """This request's own standard, only. No declaration given: the caller's stands."""
        ids = self.declared.get(job)
        return (
            claude_approved.carrying(ids)
            if ids is not None
            else contextlib.nullcontext()
        )


def _chars(packet: Packet) -> int:
    chars = len(packet.system) + len(packet.prompt)
    if packet.json_schema is not None:
        chars += _SCHEMA_WRAPPER_CHARS + len(
            json.dumps(packet.json_schema, separators=(",", ":"))
        )
    return chars


def worst_usd(model: str, packet: Packet, *, batch: bool = True) -> float:
    """The most this request can cost, at the batch price or the normal one (about twice); needs no key, so an estimate
    can run with the lane shut."""
    return claude_spend.worst_case_usd(
        model, _chars(packet), packet.num_predict, batch=batch
    )


def batches_needed(requests: int, request_bytes: int) -> int:
    """How many batches this much work takes under the API's limits."""
    return max(
        1 if requests else 0,
        math.ceil(requests / MAX_BATCH_REQUESTS),
        math.ceil(request_bytes / MAX_BATCH_BYTES),
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


def _hold(conn, run: _Run, model: str, rows: list[dict]) -> str:
    """Written BEFORE the send: a crash from here on still knows every reservation."""
    batch_row = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO claude_batches (id, job, state, model, created_at, created_epoch)"
            " VALUES (?,?,'creating',?,?,?)",
            (batch_row, rows[0]["job"], model, _now(), run.clock()),
        )
        for row in rows:
            conn.execute(
                "INSERT INTO claude_batch_requests (job, custom_id, attempts, state, batch_row, reservation_id,"
                " worst_usd, step, cache_key, api_id) VALUES (?,?,1,'held',?,?,?,?,?,?) ON CONFLICT (job, custom_id)"
                " DO UPDATE SET attempts = attempts + 1, state = 'held', batch_row = excluded.batch_row,"
                " reservation_id = excluded.reservation_id, worst_usd = excluded.worst_usd, step = excluded.step,"
                " cache_key = excluded.cache_key, api_id = excluded.api_id",
                (
                    row["job"],
                    row["custom_id"],
                    batch_row,
                    row["reservation"].id,
                    row["reservation"].worst_usd,
                    row["reservation"].step,
                    row["key"],
                    row["api_id"],
                ),
            )
    return batch_row


def _create_failed(conn, batch_row: str, rows: list[dict], exc: Exception) -> None:
    """Charged unless it provably cost nothing. A create that may have worked is "unconfirmed", never re-sent alone."""
    for row in rows:
        claude_spend.settle_failure(row["reservation"], exc, unbilled=_unbilled)
    state = "not_sent" if _unbilled(exc) else "unconfirmed"
    with conn:
        conn.execute(
            "UPDATE claude_batches SET state = ? WHERE id = ?", (state, batch_row)
        )
        conn.execute(
            "UPDATE claude_batch_requests SET state = ?, attempts = attempts - ? WHERE batch_row = ?",
            (state, 1 if _unbilled(exc) else 0, batch_row),
        )


class _Free:
    """What is still free in this send, ledger and earlier requests of it together."""

    def __init__(self, room) -> None:
        self.room, self.used, self.shared_used, self.seen = room, {}, 0.0, {}

    def fits(self, step: str, worst: float) -> bool:
        if self.room is None:
            return True
        if step not in self.seen:
            self.seen[step] = self.room(step)
        step_free, shared_free = self.seen[step]
        used = self.used.get(step, 0.0)
        if used + worst > step_free or self.shared_used + worst > shared_free:
            return False
        self.used[step] = used + worst
        self.shared_used += worst
        return True


def _prepare(run: _Run, todo: dict[str, list[str]]) -> list[dict]:
    """The bodies to send, what the answer cache already holds taken out, what does not fit left out and named."""
    conn, provider = run.conn, run.provider
    model = provider.requested_model
    free, rows, taken = _Free(run.room), [], set()
    for job, custom_ids in todo.items():
        out = run.out[job]
        for custom_id in custom_ids:
            packet = run.work[job][custom_id]
            step = provider._step or packet.step
            request, body, _prompt = provider._request(packet)
            if not run.cache_system.get(
                job, True
            ):  # would only ever pay the dearer write
                body["system"] = [
                    {k: v for k, v in block.items() if k != "cache_control"}
                    for block in body.get("system", [])
                ]
            with run.carrying(job):
                stored, key = claude_spend.answer_on_file(
                    step,
                    body,
                    version=_cache_version(packet),
                    valid=_valid_for(packet),
                    prompt_sha256=packet.sha256,
                )
            if stored is not None:
                answer = provider._response(stored, packet, 0.0, 0.0)
                _answered_elsewhere(conn, job, custom_id, answer, FROM_CACHE)
                _keep_raw(
                    conn,
                    job,
                    custom_id,
                    packet,
                    stored.get("model"),
                    FROM_CACHE,
                    stored,
                )
                out.from_cache += 1
                continue
            worst = worst_usd(model, packet)
            if not free.fits(step, worst):
                out.over_budget.append(custom_id)
                continue
            api_id = (
                custom_id if custom_id not in taken else f"d{len(taken)}-{custom_id}"
            )
            taken.add(api_id)
            rows.append(
                {
                    "job": job,
                    "custom_id": custom_id,
                    "api_id": api_id,
                    "key": key,
                    "step": step,
                    "worst": worst,
                    "request": request,
                    "params": body,
                }
            )
    return rows


def _reserve(run: _Run, rows: list[dict]) -> None:
    """Per standard, so each reservation line names its own document. One refusal takes back the rest."""
    model = run.provider.requested_model
    held = []
    try:
        for job in {row["job"] for row in rows}:
            own = [row for row in rows if row["job"] == job]
            with run.carrying(job):
                reservations = claude_spend.reserve_all(
                    [(row["step"], row["worst"]) for row in own],
                    model=model,
                    batch=True,
                )
            for row, reservation in zip(own, reservations, strict=True):
                row["reservation"] = reservation
                held.append(reservation)
    except claude_spend.StopRun:
        for reservation in held:
            claude_spend.release(reservation, "unbilled:not_sent")
        raise


def _slices(rows: list[dict]) -> list[list[dict]]:
    """As few batches as the API's limits allow."""
    out: list[list[dict]] = []
    size = 0
    for row in rows:
        bytes_ = len(json.dumps(row["params"], ensure_ascii=False).encode("utf-8"))
        if (
            not out
            or len(out[-1]) >= MAX_BATCH_REQUESTS
            or size + bytes_ > MAX_BATCH_BYTES
        ):
            out.append([])
            size = 0
        out[-1].append(row)
        size += bytes_
    return out


def _submit(run: _Run, todo: dict[str, list[str]]) -> list[str]:
    """Send `todo` in as few batches as allowed and store their ids. Returns the local batch rows."""
    conn = run.conn
    model = run.provider.requested_model
    rows = _prepare(run, todo)
    if not rows:
        return []
    _reserve(run, rows)
    made = []
    for part in _slices(rows):
        batch_row = _hold(conn, run, model, part)
        request = part[0]["request"]
        try:
            batch = run.client.batch_create(
                request["url"],
                headers=request["headers"],
                requests=[
                    {"custom_id": row["api_id"], "params": row["params"]}
                    for row in part
                ],
            )
        except Exception as exc:  # #1584: whatever failed, the reservation is settled and the rows say why
            _create_failed(conn, batch_row, part, exc)
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
        made.append(batch_row)
    return made


def _take_result(run: _Run, held: dict, result: dict, wall: float) -> None:
    """One result row, whichever position it came in."""
    conn, provider = run.conn, run.provider
    model = provider.requested_model
    job, custom_id = held["job"], held["custom_id"]
    kind = str(result.get("type"))
    reservation = _reservation(held, model)
    if kind == "succeeded":
        packet = run.work[job][custom_id]
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
        with run.carrying(job):
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


def _rows_of(run: _Run, batch_row: str) -> dict[str, dict]:
    """{what the API calls it: its row} for one local batch."""
    rows = run.conn.execute(
        "SELECT * FROM claude_batch_requests WHERE batch_row = ?", (batch_row,)
    ).fetchall()
    return {(r["api_id"] or r["custom_id"]): dict(r) for r in rows}


def _take_late(run: _Run, held: dict, result: dict) -> None:
    """A result for a request no longer waiting on this batch: another send answered it. Billed by the batch, so
    charged at the batch price; its answer is kept raw and does not replace the one in use."""
    job, custom_id = held["job"], held["custom_id"]
    run.out[job].late_results += 1
    if str(result.get("type")) != "succeeded":
        return
    message = result.get("message") or {}
    _keep_raw(
        run.conn,
        job,
        custom_id,
        run.work[job][custom_id],
        message.get("model"),
        held["api_batch_id"],
        message,
    )
    claude_spend.record(
        step=held["step"],
        model=str(message.get("model") or run.provider.requested_model),
        usage=message.get("usage"),
        prompt_sha256="",
        wall_time_s=0.0,
        finish_reason="late_batch_result",
        batch=True,
    )


def _read_ended(run: _Run, batch_row: str, batch: dict, headers: dict) -> None:
    """Take every result of an ended batch."""
    conn = run.conn
    rows = _rows_of(run, batch_row)
    started = time.time()
    results = run.client.batch_results(str(batch.get("results_url")), headers=headers)
    for row in results:
        api_id = str(row.get("custom_id"))
        held = rows.get(api_id)
        if held is None or held["custom_id"] not in run.work.get(held["job"], {}):
            for out in run.out.values():
                out.unknown_results += 1
                break
            continue
        if held["state"] == "held":
            _take_result(run, held, row.get("result") or {}, time.time() - started)
        elif held["state"] == "answered":
            _take_late(run, held, row.get("result") or {})
    missing = False
    for held in _rows_of(run, batch_row).values():  # a request the results never named
        if held["state"] == "held":
            missing = True
            _take_result(run, held, {}, time.time() - started)
    with conn:
        conn.execute(
            "UPDATE claude_batches SET state = ? WHERE id = ?",
            ("ended_missing" if missing else "ended", batch_row),
        )


def _batch_of(run: _Run, batch_row: str) -> tuple[dict, dict, str, dict]:
    found = run.conn.execute(
        "SELECT * FROM claude_batches WHERE id = ?", (batch_row,)
    ).fetchone()
    first = next(iter(run.work.values()))
    request, _body, _prompt = run.provider._request(next(iter(first.values())))
    return dict(found), request, request["url"], request["headers"]


def _poll(run: _Run, url, api_id, headers, deadline) -> dict | None:
    """The batch once it has ended, or None when `deadline` passed first."""
    batch = run.client.batch_retrieve(url, api_id, headers=headers)
    while batch.get("processing_status") != "ended":
        if run.clock() >= deadline:
            return None
        run.sleep(run.poll_seconds)
        batch = run.client.batch_retrieve(url, api_id, headers=headers)
    return batch


def _cancel_and_read(run: _Run, batch_row: str, found, url, headers) -> bool:
    """Cancel, and read the batch once it has ended. False when it did not: then nothing may be sent."""
    api_id = found["api_batch_id"]
    if found["state"] != "canceling":
        try:
            run.client.batch_cancel(url, api_id, headers=headers)
        except Exception as exc:  # noqa: BLE001 - #1584: an unsure cancel may still answer, so nothing is sent
            log.warning("batch cancel failed (%s)", type(exc).__name__)
            return False
        with run.conn:
            run.conn.execute(
                "UPDATE claude_batches SET state = 'canceling' WHERE id = ?",
                (batch_row,),
            )
    for out in run.out.values():
        out.batches_cancelled += 1
    batch = _poll(run, url, api_id, headers, run.clock() + CANCEL_WAIT_S)
    if batch is None:
        return False
    _read_ended(run, batch_row, batch, headers)
    return True


def _collect(run: _Run, batch_row: str) -> tuple[bool, bool]:
    """(ended, timed out). Wait for one batch and take its results; with a fallback, cancel one older than it."""
    found, _request, url, headers = _batch_of(run, batch_row)
    deadline = run.deadline
    if run.fallback_after_s is not None:
        born = float(found.get("created_epoch") or run.clock())
        deadline = born + run.fallback_after_s
    if found["state"] == "canceling" and run.fallback_after_s is not None:
        return _cancel_and_read(run, batch_row, found, url, headers), True
    batch = _poll(run, url, found["api_batch_id"], headers, deadline)
    if batch is None:
        if run.fallback_after_s is None:
            return False, False
        return _cancel_and_read(run, batch_row, found, url, headers), True
    _read_ended(run, batch_row, batch, headers)
    return True, False


def _open_batches(conn, jobs) -> list[str]:
    """The batches of these jobs still out. One that also holds a job not named here is refused: its results have
    nowhere to go in this run."""
    marks = ",".join("?" for _ in jobs)
    states = ",".join("?" for _ in OPEN_STATES)
    rows = conn.execute(
        "SELECT DISTINCT b.id AS id, b.created_at AS at FROM claude_batches b JOIN claude_batch_requests r"
        f" ON r.batch_row = b.id WHERE r.job IN ({marks}) AND b.state IN ({states}) ORDER BY b.created_at, b.id",
        (*jobs, *OPEN_STATES),
    ).fetchall()
    for row in rows:
        others = conn.execute(
            f"SELECT COUNT(*) AS n FROM claude_batch_requests WHERE batch_row = ? AND job NOT IN ({marks})",
            (row["id"], *jobs),
        ).fetchone()["n"]
        if others:
            raise ProviderRefused(
                f"claude: an open batch also holds {others} request(s) of a standard not named in this run; "
                "name every standard that went with it"
            )
    return [r["id"] for r in rows]


def _read_late(run: _Run) -> None:
    """A batch that ended with requests missing is read again: a row that turns up is used, not bought twice. It was
    charged its worst case when it was missing, so nothing is charged now."""
    conn = run.conn
    rows = conn.execute(
        "SELECT DISTINCT b.id AS id FROM claude_batches b JOIN claude_batch_requests r ON r.batch_row = b.id"
        f" WHERE b.state = 'ended_missing' AND r.job IN ({','.join('?' for _ in run.work)})",
        tuple(run.work),
    ).fetchall()
    for row in rows:
        found, _request, url, headers = _batch_of(run, row["id"])
        batch = run.client.batch_retrieve(url, found["api_batch_id"], headers=headers)
        by_api = _rows_of(run, row["id"])
        for item in run.client.batch_results(
            str(batch.get("results_url")), headers=headers
        ):
            held = by_api.get(str(item.get("custom_id")))
            result = item.get("result") or {}
            if (
                held is None
                or held["failure"] != NO_RESULT
                or result.get("type") != "succeeded"
                or held["custom_id"]
                not in run.work[held["job"]]  # a caller left it out
            ):
                continue
            job, custom_id = held["job"], held["custom_id"]
            message = result.get("message") or {}
            _keep_raw(
                conn,
                job,
                custom_id,
                run.work[job][custom_id],
                message.get("model"),
                held["api_batch_id"],
                message,
            )
            run.out[job].late_results += 1
            if held["state"] != "answered":
                _set(
                    conn,
                    job,
                    custom_id,
                    state="answered",
                    answer=reader_api.response_text(message).strip(),
                    model=message.get("model"),
                    finish_reason="stop",
                    failure=None,
                )
        still_missing = [
            r
            for r in _rows_of(run, row["id"]).values()
            if r["failure"] == NO_RESULT and r["state"] != "answered"
        ]
        if not still_missing:
            with conn:
                conn.execute(
                    "UPDATE claude_batches SET state = 'ended' WHERE id = ?",
                    (row["id"],),
                )


def _send_rest_normally(run: _Run) -> None:
    """The batch has ended: what it did not answer, one by one at the normal price, while its worst case fits."""
    conn, provider = run.conn, run.provider
    model = provider.requested_model
    stopped = False
    for job, packets in run.work.items():
        rows = _state(conn, job)
        out = run.out[job]
        out.over_budget = []  # what the batch could not fit is weighed again, at this price and what is free now
        for custom_id, packet in packets.items():
            row = rows.get(custom_id)
            if row and row["state"] in ("answered", "held", "unconfirmed"):
                continue
            step = provider._step or packet.step
            step_free, shared_free = (
                run.room(step) if run.room else (math.inf, math.inf)
            )
            worst = worst_usd(model, packet, batch=False)
            if stopped or worst > step_free or worst > shared_free:
                out.over_budget.append(custom_id)
                continue
            try:
                with run.carrying(job):
                    answer = provider.reason(packet)
            except claude_spend.DocumentNotApproved:
                raise
            except claude_spend.StopRun:
                out.over_budget.append(custom_id)
                continue
            except ProviderRefused:
                # A failed call may have been charged; do not keep paying into a failure. The rest is named.
                out.over_budget.append(custom_id)
                stopped = True
                continue
            _keep_raw(
                conn,
                job,
                custom_id,
                packet,
                answer.model_tag,
                NORMAL_SEND,
                {
                    "model": answer.model_tag,
                    "stop_reason": answer.finish_reason,
                    "content": list(answer.content_blocks)
                    or [{"type": "text", "text": answer.text}],
                    "usage": {
                        "input_tokens": answer.tokens_in,
                        "output_tokens": answer.tokens_out,
                    },
                    "sent": NORMAL_SEND,
                },
            )
            _answered_elsewhere(conn, job, custom_id, answer, NORMAL_SEND)
            out.sent_normal += 1


def _todo(run: _Run, again) -> dict[str, list[str]]:
    todo = {}
    for job, packets in run.work.items():
        rows = _state(run.conn, job)
        left = run.out[job].over_budget
        wanted = [
            c
            for c in packets
            if (c not in rows or rows[c]["state"] in again) and c not in left
        ]
        if wanted:
            todo[job] = wanted
    return todo


def _results(run: _Run) -> dict[str, Outcome]:
    return {
        job: _finish(run.conn, job, packets, run.out[job])
        for job, packets in run.work.items()
    }


def run_many(
    conn,
    provider: ClaudeProvider,
    work: dict[str, dict[str, Packet]],
    *,
    client=None,
    room=None,
    usable=None,
    poll_seconds: float = 60.0,
    max_wait_s: float = 86400.0,
    sleep=time.sleep,
    clock=time.time,
    resend_unconfirmed: bool = False,
    cache_system: dict[str, bool] | None = None,
    declared: dict[str, set[str]] | None = None,
    fallback_after_s: float | None = None,
) -> dict[str, Outcome]:
    """Answer every packet of every job, or say which were not, in as few batches as the API allows. Open batches are read
    first, so a run after a crash polls what it already paid for; only then is anything new sent. `room(step)` is
    (USD free on this step, USD free in total and today): what does not fit is left out."""
    ensure_schema(conn)
    if client is None:
        from . import reader_transport

        if not reader_transport.available():
            raise ProviderRefused(
                "claude: egress is disabled (STANDARDS_READER_ENABLED / STANDARDS_READER_ALLOW_PUBLIC_EGRESS)"
            )
        client = reader_transport
    run = _Run(
        conn,
        provider,
        work,
        client,
        room,
        declared or {},
        cache_system or {},
        {job: Outcome() for job in work},
        poll_seconds,
        sleep,
        clock,
        clock() + max_wait_s,
        fallback_after_s,
    )
    _read_late(run)  # before re-opening: a late row is what a re-send would buy
    for job in work:
        _mark_unconfirmed(conn, job)
        _reopen(conn, job, usable)
    timed_out = False
    for batch_row in _open_batches(conn, list(work)):
        for out in run.out.values():
            out.resumed_batches += 1
        ended, late = _collect(run, batch_row)
        timed_out = timed_out or late
        if not ended:
            return _waiting(run)
    again = ("retry", "not_sent") + (("unconfirmed",) if resend_unconfirmed else ())
    while not timed_out:
        todo = _todo(run, again)
        if not todo:
            return _results(run)
        for batch_row in _submit(run, todo):
            ended, late = _collect(run, batch_row)
            timed_out = timed_out or late
            if not ended:
                return _waiting(run)
    _send_rest_normally(run)
    return _results(run)


def _waiting(run: _Run) -> dict[str, Outcome]:
    for out in run.out.values():
        out.waiting = True
    return _results(run)


def run(
    conn,
    provider: ClaudeProvider,
    job: str,
    packets: dict[str, Packet],
    *,
    cache_system: bool = True,
    **kw,
) -> Outcome:
    """One job's `run_many`."""
    return run_many(
        conn, provider, {job: packets}, cache_system={job: cache_system}, **kw
    )[job]
