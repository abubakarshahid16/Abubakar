"""The AI clause review on the Claude lane: every applicable requirement, by Message Batch.

The local path (`clause_review.run`) keeps its per-run limit. This path runs ONLY when the step's own
engine setting says so (`AI_CLAUSE_REVIEW_ENGINE=claude`, default local) and `rp.claude_for_task` finds
the lane open and every carried document on the approved list and not blocked. Otherwise the review stays
where it was, and says why. AI proposes, code verifies the quote (`clause_review._classify`), the engineer
decides: rows are the same NEEDS_ENGINEER_REVIEW suggestions, never a verdict, never "checked".

WHAT ONE ASK CARRIES. One requirement and its few small passages (`clause_review.retrieve`, keyword only, no
local model). Never a whole document or a library.

WHO HOLDS WHAT. Spend, approval, answer cache and crash recovery are `claude_batch_run`'s (#1584), which goes
through `reader_transport`, `claude_spend.reserve_all` and `claude_answer_cache`. This file only asks it.

THE USD CAP IS NEVER RAISED. Every request is reserved at its worst case and `room()` says what the caps leave,
so a batch cannot cross them. What does not fit waits for the next tick: once the batch settles at its real cost
the room grows, and the next tranche goes. When the room no longer fits one more ask, the run closes partial and
counts what was not reviewed. Step `clause_review` is one line of the ledger, across all runs.

WAITING DOES NOT BLOCK THE APP. `for_review` submits and returns, never sleeping (`max_wait_s=0`); the review job
finishes, and its CRS and audit say "pending". `poll_due` runs from the idle worker loop, one poll every
`clause_review_batch_poll_seconds`. The state is in the database, so a restart polls the same batch and never pays
twice. Past `clause_review_batch_wait_hours` the run closes and what did not return is counted not reviewed; a
request still open stays charged at its worst case, which errs toward spent. The lane shut while waiting: no poll.

A SEAM OF `claude_batch_run.run`: it re-queues given-up requests each time it is called, because it was written
for one call per run. A polling caller must not resend them, so they are read before each call, kept here and
left out of the packets it is given. Expired or cancelled twice is not reviewed; errored or lost is failed.

Stored here: ids, counts and closed words. Raw answers in the batch tables are removed at the close and when the
submittal is deleted. Logged: error type only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time

from . import (
    access,
    claude_approved,
    claude_batch_run,
    claude_spend,
    clause_review,
    clause_review_status,
)
from . import reasoning_provider as rp
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

STEP = clause_review.STEP
PROMPT_VERSION = "clause-review-claude-v1"
JOB_PREFIX = "clause_review:"
ENGINE_LABEL = "claude_batch"
#: The answer is one short JSON object; `claude_spend.output_cap` raises this for a model that thinks by default.
MAX_OUTPUT_TOKENS = 1024
PENDING, CLOSED = "pending", "closed"
#: `claude_batch_run` failure words that mean the API never did the work.
NOT_DONE_WORDS = ("expired", "canceled")

WHY_WAITING = "the Claude batch has not returned yet"
WHY_GONE = "the requirement is no longer in the library"
WHY_UNCONFIRMED = "the batch may have been created but its id was lost; it stays charged and is not sent again"

_TABLE = """CREATE TABLE IF NOT EXISTS clause_review_batches (
    review_run_id TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    state         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    kind_state    TEXT NOT NULL,
    model         TEXT NOT NULL,
    asks          TEXT NOT NULL,
    documents     TEXT NOT NULL,
    gave_up       TEXT NOT NULL DEFAULT '{}',
    reasons       TEXT NOT NULL DEFAULT '{}',
    written       TEXT NOT NULL DEFAULT '[]',
    worst_all     REAL NOT NULL DEFAULT 0,
    started_at    REAL NOT NULL,
    next_poll_at  REAL NOT NULL,
    deadline_at   REAL NOT NULL
)"""

#: Packets rebuilt once per process per run: retrieval of hundreds of asks is not a thing to repeat every poll.
_PACKETS: dict[str, dict[str, rp.Packet]] = {}


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    conn.execute(_TABLE)
    claude_batch_run.ensure_schema(conn)


def _engine() -> str:
    return str(settings.ai_clause_review_engine or "").strip().lower()


def _job(review_run_id: str) -> str:
    return JOB_PREFIX + review_run_id


def _custom_id(requirement_id: str) -> str:
    return "r" + hashlib.sha256(str(requirement_id).encode("utf-8")).hexdigest()[:40]


def _client():
    """The batch transport. None: `claude_batch_run` uses `reader_transport`, its one lane."""
    return


def _system(kind: str) -> str:
    """The stable part, sent as the cached system block, so asks after the first read it at the cache price."""
    return clause_review.SYSTEM + "\n\n" + clause_review.examples_prefix(kind)


def packet_for(kind: str, requirement: dict, passages: list[dict]) -> rp.Packet:
    return rp.Packet(
        prompt=clause_review.question(requirement, passages),
        system=_system(kind),
        num_ctx=0,
        num_predict=MAX_OUTPUT_TOKENS,
        json_schema=clause_review.SCHEMA,
        step=STEP,
        prompt_version=PROMPT_VERSION,
    )


def _requirements(asks: dict[str, str]) -> dict[str, dict]:
    """custom_id -> requirement, for those still in the library."""
    conn = connect()
    out = {}
    for custom_id, requirement_id in asks.items():
        row = conn.execute(
            "SELECT id, standard_document_id, clause, page, requirement_text, source_text"
            " FROM standard_requirements WHERE id = ?",
            (requirement_id,),
        ).fetchone()
        if row is not None:
            out[custom_id] = dict(row)
    return out


def _build_packets(submittal: str, kind: str, requirements: dict[str, dict]) -> dict:
    pages = clause_review.page_texts(submittal)
    return {
        custom_id: packet_for(
            kind, req, clause_review.retrieve(submittal, req["requirement_text"], pages)
        )
        for custom_id, req in requirements.items()
    }


def _room() -> float:
    """The USD the caps still leave this step; `claude_batch_run` sends only what fits it at worst case."""
    caps = claude_spend.Caps.from_settings().for_step(STEP)
    return max(
        0.0,
        min(
            caps.per_step - claude_spend.spent(STEP), caps.total - claude_spend.spent()
        ),
    )


def _why_cap() -> str:
    caps = claude_spend.Caps.from_settings().for_step(STEP)
    return (
        f"the USD {caps.per_step:g} cap of step {STEP} or the USD {caps.total:g} total cap would be "
        "crossed (a cap is the owner's decision)"
    )


def _usd(review_run_id: str, worst_all: float) -> dict:
    charged = held = 0.0
    for line in claude_spend.entries():
        if line.get("run") == review_run_id and line.get("step") == STEP:
            if line.get("reserved"):
                held += float(line.get("cost_usd") or 0)
            else:
                charged += float(line.get("cost_usd") or 0)
    return {
        "charged": round(charged, 6),
        "held": round(held, 6),
        "worst_case_all": round(worst_all, 4),
    }


def _sent(review_run_id: str) -> int:
    """Asks that went to the API at least once, whatever came back; a stored answer is not one."""
    return (
        connect()
        .execute(
            "SELECT COUNT(*) FROM claude_batch_requests WHERE job = ? AND"
            " ((api_batch_id IS NOT NULL AND api_batch_id <> ?) OR state = 'unconfirmed')",
            (_job(review_run_id), claude_batch_run.FROM_CACHE),
        )
        .fetchone()[0]
    )


def _reading(answered: dict) -> dict | None:
    """The answer as `clause_review._classify` takes it; a cut-off or schema-breaking reply is no answer."""
    from .ai.json_reply import unfenced_whole

    if answered.get("finish_reason") == "length":
        return None
    text = unfenced_whole(answered.get("text") or "")
    if rp.schema_errors(text, clause_review.SCHEMA):
        return None
    return clause_review._parse(text)


def _loads(row, column: str):
    return json.loads(row[column])


def _status(row, answers, gave_up, reasons, requirements, pending, now) -> dict:
    """Every ask lands in exactly one count. Pure but for the page read and the ledger."""
    asks = _loads(row, "asks")
    pages = clause_review.page_texts(row["document_id"])
    readable = [p for p, t in pages.items() if t.strip()]
    status = clause_review._start_status(
        row["kind"], row["kind_state"], row["model"], len(readable), 0.0, len(asks)
    )
    status.update(engine=ENGINE_LABEL, prompt_version=PROMPT_VERSION, pending=pending)
    why: dict[str, int] = {}
    for custom_id, requirement_id in asks.items():
        req = requirements.get(custom_id)
        label = clause_review._label(req) if req else requirement_id
        if custom_id in answers:
            outcome, _page, _quote = clause_review._classify(
                _reading(answers[custom_id]), pages
            )
            status[outcome] += 1
            if answers[custom_id].get("batch_id") == claude_batch_run.FROM_CACHE:
                status["cache_hits"] += 1
            continue
        word = gave_up.get(custom_id)
        if word is not None and word not in NOT_DONE_WORDS:
            status["failed"].append(label)
            continue
        if word is not None:
            reason = f"its batch request {word} twice"
        elif req is None:
            reason = WHY_GONE
        else:
            reason = reasons.get(custom_id) or WHY_WAITING
        why[reason] = why.get(reason, 0) + 1
        status["not_reviewed"].append(label)
    status["not_reviewed_why"] = why
    status["stopped"] = "; ".join(why) or None
    status["calls"] = _sent(row["review_run_id"])
    status["usd"] = _usd(row["review_run_id"], float(row["worst_all"]))
    clause_review_status.fill(status, max(0.0, now - float(row["started_at"])))
    return status


def _write_rows(row, answers, requirements, written: set[str]) -> None:
    """Rows for the answers not yet written; code classifies, the row stays a suggestion."""
    pages = clause_review.page_texts(row["document_id"])
    for custom_id, answered in answers.items():
        req = requirements.get(custom_id)
        if custom_id in written or req is None:
            continue
        outcome, page, quote = clause_review._classify(_reading(answered), pages)
        clause_review._store_row(
            row["review_run_id"],
            row["document_id"],
            req,
            outcome,
            page,
            quote,
            f"{rp.CLAUDE}:{answered.get('model') or row['model']}",
            answered.get("batch_id") == claude_batch_run.FROM_CACHE,
        )
        written.add(custom_id)


def _save(conn, row, *, state, gave_up, reasons, written, next_poll) -> None:
    with conn:
        conn.execute(
            "UPDATE clause_review_batches SET state = ?, gave_up = ?, reasons = ?, written = ?,"
            " next_poll_at = ? WHERE review_run_id = ?",
            (
                state,
                json.dumps(gave_up),
                json.dumps(reasons),
                json.dumps(sorted(written)),
                next_poll,
                row["review_run_id"],
            ),
        )


def _purge(conn, job: str) -> None:
    """Raw answers leave the batch tables; the rows hold only what code verified. Spend stays in the ledger."""
    with conn:
        conn.execute("DELETE FROM claude_batch_answers WHERE job = ?", (job,))
        conn.execute(
            "UPDATE claude_batch_requests SET answer = NULL WHERE job = ?", (job,)
        )


def forget_documents(conn, document_ids) -> None:
    """A deleted submittal's raw answers go with it, inside the delete's own transaction."""
    exists = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'clause_review_batches'"
    if conn.execute(exists).fetchone() is None:
        return
    for document_id in document_ids:
        rows = conn.execute(
            "SELECT review_run_id FROM clause_review_batches WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        for found in rows:
            job = _job(found["review_run_id"])
            conn.execute("DELETE FROM claude_batch_answers WHERE job = ?", (job,))
            conn.execute("DELETE FROM claude_batch_requests WHERE job = ?", (job,))
            _PACKETS.pop(found["review_run_id"], None)


def _after_close(review_run_id: str) -> None:
    """Number the rows that arrived and write the audit again (phase times stay on the stored trace).
    Never raises: the rows are stored."""
    from . import review_audit, review_jobs
    from .main import number_crs_rows

    try:
        job = (
            connect()
            .execute(
                "SELECT created_by FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
                (review_run_id,),
            )
            .fetchone()
        )
        if job is None:
            return
        requester = access.AccessScope(
            user_id=job["created_by"],
            allowed_document_ids=review_jobs._scope_of(job["created_by"]),
        )
        number_crs_rows(review_run_id, requester)
        review_audit.write(review_run_id, requester, None)
    except Exception as exc:  # noqa: BLE001 - a late write never breaks the stored rows
        log.warning("clause review close: %s", type(exc).__name__)


def _settled(conn, job: str, ids: set[str], gave_up: dict) -> dict:
    """Read what was given up BEFORE `run` can re-queue it, and keep it."""
    earlier = claude_batch_run.stored_outcome(conn, job, ids)
    return {**gave_up, **earlier.gave_up}


def tick(review_run_id: str, *, provider=None, now=time.time) -> dict | None:
    """One non-blocking step: read a batch if it ended, send what fits, write rows, store the honest status."""
    conn = connect()
    ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM clause_review_batches WHERE review_run_id = ?", (review_run_id,)
    ).fetchone()
    if row is None or row["state"] == CLOSED:
        return clause_review.status_of(review_run_id)
    job = _job(review_run_id)
    run_row = conn.execute(
        "SELECT status FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    if run_row is None or run_row["status"] == "cancelled":
        with conn:
            conn.execute(
                "UPDATE clause_review_batches SET state = ? WHERE review_run_id = ?",
                (CLOSED, review_run_id),
            )
        _purge(conn, job)
        _PACKETS.pop(review_run_id, None)
        return None
    asks = _loads(row, "asks")
    requirements = _requirements(asks)
    gave_up = _settled(conn, job, set(asks), _loads(row, "gave_up"))
    reasons, written = _loads(row, "reasons"), set(_loads(row, "written"))
    _save(
        conn,
        row,
        state=PENDING,
        gave_up=gave_up,
        reasons=reasons,
        written=written,
        next_poll=now() + float(settings.clause_review_batch_poll_seconds),
    )
    outcome, stop = None, None
    with (
        claude_approved.carrying(_loads(row, "documents")),
        claude_spend.for_run(review_run_id),
    ):
        provider = provider or rp.claude_for_task(_engine(), step=STEP)
        packets = _PACKETS.get(review_run_id)
        if provider is not None and packets is None:
            packets = _build_packets(row["document_id"], row["kind"], requirements)
            _PACKETS[review_run_id] = packets
        live = {c: p for c, p in (packets or {}).items() if c not in gave_up}
        if provider is not None and not live:
            stop = ""  # every ask has an end: nothing to send, nothing to wait for
        elif live and provider is not None:
            try:
                outcome = claude_batch_run.run(
                    conn,
                    provider,
                    job,
                    live,
                    client=_client(),
                    room=_room,
                    poll_seconds=0.0,
                    max_wait_s=0.0,
                    sleep=lambda _s: None,
                )
            except claude_spend.StopRun as exc:
                stop = claude_spend.refusal_words(exc, _why_cap())
            except rp.ProviderRefused as exc:
                stop = f"the batch was not accepted ({exc})"
            except Exception as exc:  # noqa: BLE001 - a failed poll settles nothing: the next tick reads the batch again
                log.warning("clause review poll: %s", type(exc).__name__)
    stored = claude_batch_run.stored_outcome(conn, job, set(asks))
    gave_up = {**gave_up, **stored.gave_up}
    answers = stored.answers
    _write_rows(row, answers, requirements, written)
    waiting = outcome is None or outcome.waiting
    unanswered = [
        c for c in asks if c not in answers and c not in gave_up and c in requirements
    ]
    if stop is None and outcome is not None and not waiting:
        for custom_id in stored.unconfirmed:
            reasons[custom_id] = WHY_UNCONFIRMED
        open_asks = [c for c in unanswered if c not in stored.unconfirmed]
        fits = (
            outcome.over_budget
            and packets
            and _room()
            >= claude_batch_run.worst_usd(
                provider.requested_model, packets[outcome.over_budget[0]]
            )
        )
        if outcome.over_budget and not fits:
            stop = _why_cap()
        elif not open_asks:
            stop = ""  # nothing left to wait for
    if stop is None and now() >= float(row["deadline_at"]):
        hours = float(settings.clause_review_batch_wait_hours)
        stop = f"the batch did not return within {hours:g} h"
    closing = stop is not None
    if stop:
        for custom_id in unanswered:
            reasons.setdefault(custom_id, stop)
    status = _status(row, answers, gave_up, reasons, requirements, not closing, now())
    _save(
        conn,
        row,
        state=CLOSED if closing else PENDING,
        gave_up=gave_up,
        reasons=reasons,
        written=written,
        next_poll=now() + float(settings.clause_review_batch_poll_seconds),
    )
    clause_review._store_status(review_run_id, status)
    if closing:
        _purge(conn, job)
        _PACKETS.pop(review_run_id, None)
        _after_close(review_run_id)
    return status


def _why_not_claude(documents) -> str:
    code = rp.claude_unavailable_for_task(_engine())[0]
    if code is None:
        with claude_approved.carrying(documents):
            refused = claude_approved.refusal()
        code = refused[0] if refused else "not available"
    return f"Claude was asked for and not used ({code})"


def for_review(
    review_run_id: str, scope: frozenset[str], *, provider=None
) -> tuple[bool, str | None]:
    """(handled here, why the Claude lane was not used). Submits and returns; never waits for the batch."""
    from . import submittal_review

    if _engine() != rp.CLAUDE:
        return False, None
    run_row = submittal_review.get_review_run(review_run_id, allowed_document_ids=scope)
    if run_row is None:
        return True, None
    submittal = run_row["submittal_document_id"]
    kind, state = clause_review.eligible(submittal)
    if kind is None:
        return True, None
    wanted = clause_review.requirements_for(review_run_id, scope)
    documents = sorted({submittal, *(r["standard_document_id"] for r in wanted)})
    with claude_approved.carrying(documents):
        provider = provider or rp.claude_for_task(_engine(), step=STEP)
    if provider is None:
        return False, _why_not_claude(documents)
    conn = connect()
    ensure_schema(conn)
    asks = {_custom_id(r["id"]): r["id"] for r in wanted}
    packets = _build_packets(submittal, kind, {_custom_id(r["id"]): r for r in wanted})
    _PACKETS[review_run_id] = packets
    worst = sum(
        claude_batch_run.worst_usd(provider.requested_model, p)
        for p in packets.values()
    )
    started = time.time()
    with conn:  # a retried job keeps its row, and so its batch: never paid twice
        conn.execute(
            "INSERT OR IGNORE INTO clause_review_batches (review_run_id, document_id, state, kind, kind_state,"
            " model, asks, documents, worst_all, started_at, next_poll_at, deadline_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                review_run_id,
                submittal,
                PENDING,
                kind,
                state,
                provider.requested_model,
                json.dumps(asks),
                json.dumps(documents),
                worst,
                started,
                started,
                started + float(settings.clause_review_batch_wait_hours) * 3600.0,
            ),
        )
    tick(review_run_id, provider=provider)
    return True, None


def poll_due(*, provider=None, now=time.time) -> int:
    """The idle worker's call: tick each run whose poll is due. Returns how many. Never raises."""
    with contextlib.suppress(Exception):
        conn = connect()
        exists = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'clause_review_batches'"
        if conn.execute(exists).fetchone() is None:
            return 0
        rows = conn.execute(
            "SELECT review_run_id FROM clause_review_batches WHERE state = ? AND next_poll_at <= ?",
            (PENDING, now()),
        ).fetchall()
        for found in rows:
            try:
                tick(found["review_run_id"], provider=provider, now=now)
            except Exception as exc:  # noqa: BLE001 - one run's poll never stops the worker
                log.warning("clause review poll: %s", type(exc).__name__)
        return len(rows)
    return 0
