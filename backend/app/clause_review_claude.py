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
counts what was not reviewed. The caps are `claude_spend`'s, read by `_room` (owner on #1584, 2 Nov 2026: USD 10 for this
step and USD 15 for one review run). May run on Claude when its switch is on; the live default stays local until the
A/B proof is posted.

WAITING DOES NOT BLOCK THE APP. `for_review` submits and returns, never sleeping (`max_wait_s=0`); the review job
finishes, and its CRS and audit say "pending". `poll_due` runs from the idle worker loop, one poll every
`clause_review_batch_poll_seconds`. The state is in the database, so a restart polls the same batch and never pays
twice. The lane shut while waiting: no poll.

PAST `clause_review_batch_wait_hours` TWO THINGS ARE KEPT APART. An ask never sent is counted "never sent" and is not
sent any more. An ask sent is paid for or may be, so its batch is still read, hourly, for
`clause_review_batch_read_days` (how long the API keeps results): the run stays pending and says "sent, not read yet",
and a result read late settles at its real cost and gets its row. Only after that is it closed, charged at its worst
case and marked estimated, because the bill is unknown. A failed poll or a shut lane never loses a paid result.

A DECISION IS NOT WRITTEN UNDER. A run with an engineer's final code gets no late rows (`comparison.run_comparison`
refuses a re-run for the same reason). The answers stay in the answer cache, so a new review reads them at no cost.

A RETRIED JOB RE-RUNS THE COMPARISON, WHICH DELETES UNDECIDED ROWS, and this run's rows go with them. So `written` is
checked against the stored rows on every entry. A missing row comes back from the batch tables while pending, and after
the close from the answer cache (a USD 0 cache line, no send, no charge). An answer the cache no longer holds is counted
not reviewed and is not bought again.

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
    claude_spend_report,
    clause_review,
    clause_review_kind,
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
WHY_NOT_YET = "it has not been sent to Claude yet"
WHY_LOST = (
    "its row was removed when the review re-ran and its stored answer can no longer be read; "
    "it is not sent again"
)
WHY_DECIDED = (
    "the run has an engineer's final code, so its late answer gets no row; a new review reads it "
    "from the stored answers at no cost"
)
LATE_POLL_SECONDS = 3600.0
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
    written       TEXT NOT NULL DEFAULT '{}',
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


def _system(kind: str, state: str | None) -> str:
    """The stable part, sent as the cached system block, so asks after the first read it at the cache price."""
    base = clause_review_kind.system(clause_review.SYSTEM, kind, state)
    return base + "\n\n" + clause_review.examples_prefix(kind)


def packet_for(
    kind: str, requirement: dict, passages: list[dict], state: str | None = None
) -> rp.Packet:
    return rp.Packet(
        prompt=clause_review.question(requirement, passages),
        system=_system(kind, state),
        num_ctx=0,
        num_predict=MAX_OUTPUT_TOKENS,
        json_schema=clause_review_kind.schema(clause_review.SCHEMA, kind, state),
        step=STEP,
        prompt_version=clause_review_kind.version(PROMPT_VERSION, kind, state),
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


def _build_packets(submittal: str, kind: str, state, requirements: dict[str, dict]) -> dict:
    pages = clause_review.page_texts(submittal)
    return {
        custom_id: packet_for(
            kind, req, clause_review.retrieve(submittal, req["requirement_text"], pages), state
        )
        for custom_id, req in requirements.items()
    }


def _room(step: str = STEP) -> tuple[float, float]:
    """(USD free on this step in this run, USD free across this run, the total and today), the runner's `room`, read as
    `claude_spend` counts its caps, so a batch is trimmed here and not refused whole there. Inside `for_run` only. A hair
    under, for the ledger's rounding."""
    caps = claude_spend.Caps.from_settings().for_step(step)
    shared = min(
        caps.total - claude_spend.spent(),
        claude_spend_report.run_cap() - claude_spend.run_spent(),
        claude_spend_report.day_cap()
        - claude_spend_report.charged_today(claude_spend.entries()),
    )
    return caps.per_step - claude_spend.step_spent(step) - 0.00001, shared - 0.00001


def _why_cap() -> str:
    caps = claude_spend.Caps.from_settings().for_step(STEP)
    return (
        f"the USD {caps.per_step:g} cap of step {STEP} in this review run, the USD "
        f"{claude_spend_report.run_cap():g} cap per review run, the USD {claude_spend_report.day_cap():g} a day "
        f"or the USD {caps.total:g} total cap would be crossed (a cap is the owner's decision)"
    )


def _usd(review_run_id: str, worst_all: float) -> dict:
    charged = held = estimated = 0.0
    for line in claude_spend.entries():
        if line.get("run") == review_run_id and line.get("step") == STEP:
            cost = float(line.get("cost_usd") or 0)
            if line.get("reserved"):
                held += cost
            else:
                charged += cost
                estimated += cost if line.get("estimated") else 0.0
    return {
        "charged": round(charged, 6),
        "held": round(held, 6),
        "estimated": round(estimated, 6),
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


def _status(row, written, gave_up, reasons, requirements, pending, now) -> dict:
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
        if custom_id in written:
            outcome, cached = written[custom_id]
            if outcome == clause_review_kind.NOT_FOR_KIND:
                status.setdefault(outcome, []).append(label)
            else:
                status[outcome] += 1
            status["cache_hits"] += 1 if cached else 0
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


def _written(row) -> dict[str, list]:
    """custom_id -> [outcome, from stored answers], for each ask that got a row. Counts and words only."""
    found = _loads(row, "written")
    return found if isinstance(found, dict) else {}


def _store(row, req, answer, pages, model, cached, written, custom_id) -> None:
    outcome, page, quote = clause_review._classify(answer, pages)
    if clause_review_kind.not_for_kind(
        answer, outcome, req, row["kind"], row["kind_state"]
    ):
        written[custom_id] = [clause_review_kind.NOT_FOR_KIND, cached]
        return
    clause_review._store_row(
        row["review_run_id"], row["document_id"], req, outcome, page, quote,
        f"{rp.CLAUDE}:{model or row['model']}", cached,
    )  # fmt: skip
    written[custom_id] = [outcome, cached]


def _write_rows(row, answers, requirements, written: dict) -> None:
    """Rows for the answers not yet written; code classifies, the row stays a suggestion."""
    pages = clause_review.page_texts(row["document_id"])
    for custom_id, answered in answers.items():
        req = requirements.get(custom_id)
        if custom_id in written or req is None:
            continue
        cached = answered.get("batch_id") == claude_batch_run.FROM_CACHE
        _store(
            row, req, _reading(answered), pages, answered.get("model"), cached,
            written, custom_id,
        )  # fmt: skip


def _missing_rows(conn, row, written: dict) -> list[str]:
    """Asks that got a row which is gone: a re-run comparison deleted it. A decided row is not deleted."""
    asks = _loads(row, "asks")
    held = {
        r["requirement_id"]
        for r in conn.execute(
            "SELECT requirement_id FROM review_findings WHERE review_run_id = ? AND origin = ?",
            (row["review_run_id"], clause_review.ORIGIN),
        )
    }
    return [
        c
        for c, (outcome, _cached) in written.items()
        if asks[c] not in held and outcome != clause_review_kind.NOT_FOR_KIND
    ]


def _cached_answer(reader, row, req, pages) -> tuple[dict | None, str | None]:
    """(the answer, its model) from the answer cache, by the same request. Opens no socket and reserves nothing."""
    passages = clause_review.retrieve(
        row["document_id"], req["requirement_text"], pages
    )
    packet = packet_for(row["kind"], req, passages, row["kind_state"])
    try:
        _request, body, _prompt = reader._request(packet)
        stored, _key = rp._stored_answer(STEP, body, packet)
    except (rp.ProviderRefused, claude_spend.StopRun):
        return None, None
    if stored is None:
        return None, None
    told = reader._response(stored, packet, 0.0, 0.0)
    answered = {"text": told.text, "finish_reason": told.finish_reason}
    return _reading(answered), told.model_tag


def _restore_closed(row, provider, written, missing, reasons) -> None:
    """After the close the raw answers are gone: rows come back from the answer cache, at no cost. An unreadable
    answer's row needs no text. What cannot be restored is counted, and never bought again."""
    asks = _loads(row, "asks")
    requirements = _requirements({c: asks[c] for c in missing})
    pages = clause_review.page_texts(row["document_id"])
    with claude_approved.carrying(_loads(row, "documents")):
        open_lane = provider or rp.claude_for_task(_engine(), step=STEP)
        reader = rp.ClaudeProvider(row["model"], step=STEP) if open_lane else None
        for custom_id in missing:
            req = requirements.get(custom_id)
            outcome, cached = written.pop(custom_id)
            if req is None:
                continue
            if outcome == "unreadable":
                _store(row, req, None, pages, None, cached, written, custom_id)
                continue
            answer, model = (
                _cached_answer(reader, row, req, pages) if reader else (None, None)
            )
            if answer is None:
                reasons[custom_id] = WHY_LOST
                continue
            _store(row, req, answer, pages, model, cached, written, custom_id)


def _reenter_closed(conn, row, provider, now) -> dict | None:
    """A closed run entered again, by a retried job: nothing is sent; only a row or a status that was lost comes back."""
    review_run_id = row["review_run_id"]
    written, reasons = _written(row), _loads(row, "reasons")
    decided = _decided(conn, review_run_id)
    missing = [] if decided else _missing_rows(conn, row, written)
    known = clause_review.status_of(review_run_id)
    if known and not missing:
        return known
    if missing:
        _restore_closed(row, provider, written, missing, reasons)
    gave_up = _loads(row, "gave_up")
    requirements = _requirements(_loads(row, "asks"))
    status = _status(row, written, gave_up, reasons, requirements, False, now())
    _save(conn, row, CLOSED, gave_up, reasons, written, now())
    clause_review._store_status(review_run_id, status)
    _after_close(review_run_id, rows_added=not decided)
    return status


def _decided(conn, review_run_id: str) -> bool:
    """The run carries an engineer's final code: its findings are a decision (`comparison.run_comparison`)."""
    found = conn.execute(
        "SELECT engineer_final_code FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    return bool(found and found["engineer_final_code"])


def _save(conn, row, state, gave_up, reasons, written, next_poll) -> None:
    with conn:
        conn.execute(
            "UPDATE clause_review_batches SET state = ?, gave_up = ?, reasons = ?, written = ?,"
            " next_poll_at = ? WHERE review_run_id = ?",
            (
                state,
                json.dumps(gave_up),
                json.dumps(reasons),
                json.dumps(written),
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


def _sent_out(conn, job: str) -> set[str]:
    """Asks in a batch whose results were not read: sent, so possibly paid for."""
    rows = conn.execute(
        "SELECT custom_id FROM claude_batch_requests WHERE job = ? AND state = 'held'",
        (job,),
    ).fetchall()
    return {r["custom_id"] for r in rows}


def _charge_unread(conn, job: str, model: str) -> None:
    """Nothing more will be read: what is still held is charged at its worst case and marked estimated. The bill is
    unknown, so never less than it might be; the invoice is the truth. Each reservation is closed once."""
    still_open = {
        e.get("reservation") for e in claude_spend.entries() if e.get("reserved")
    }
    rows = conn.execute(
        "SELECT * FROM claude_batch_requests WHERE job = ? AND state IN ('held', 'unconfirmed')",
        (job,),
    ).fetchall()
    for found in rows:
        if found["reservation_id"] not in still_open:
            continue
        claude_spend.settle(
            claude_batch_run._reservation(dict(found), model),
            usage=None,
            finish_reason="failed:batch_not_read",
            estimated_usd=float(found["worst_usd"]),
        )


def forget_documents(conn, document_ids) -> None:
    """A deleted submittal's raw answers go with it, inside the delete's own transaction."""
    exists = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'clause_review_batches'"
    if conn.execute(exists).fetchone() is None:
        return
    for document_id in document_ids:
        rows = conn.execute(
            "SELECT review_run_id, model FROM clause_review_batches WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        for found in rows:
            job = _job(found["review_run_id"])
            with claude_spend.for_run(found["review_run_id"]):
                _charge_unread(conn, job, found["model"])
            conn.execute("DELETE FROM claude_batch_answers WHERE job = ?", (job,))
            conn.execute("DELETE FROM claude_batch_requests WHERE job = ?", (job,))
            _PACKETS.pop(found["review_run_id"], None)


def _after_close(review_run_id: str, *, rows_added: bool = True) -> None:
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
        if rows_added:
            number_crs_rows(review_run_id, requester)
        review_audit.write(review_run_id, requester, None)
    except Exception as exc:  # noqa: BLE001 - a late write never breaks the stored rows
        log.warning("clause review close: %s", type(exc).__name__)


def _settled(conn, job: str, ids: set[str], gave_up: dict) -> dict:
    """Read what was given up BEFORE `run` can re-queue it, and keep it."""
    earlier = claude_batch_run.stored_outcome(conn, job, ids)
    return {**gave_up, **earlier.gave_up}


def _run_is_gone(conn, review_run_id: str) -> bool:
    """A cancelled or deleted run is closed: no poll, no answer kept."""
    found = conn.execute(
        "SELECT status FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    if found is not None and found["status"] != "cancelled":
        return False
    row = conn.execute(
        "SELECT model FROM clause_review_batches WHERE review_run_id = ?",
        (review_run_id,),
    ).fetchone()
    with claude_spend.for_run(review_run_id):
        _charge_unread(conn, _job(review_run_id), row["model"])
    with conn:
        conn.execute(
            "UPDATE clause_review_batches SET state = ? WHERE review_run_id = ?",
            (CLOSED, review_run_id),
        )
    _purge(conn, _job(review_run_id))
    _PACKETS.pop(review_run_id, None)
    return True


def _ask(conn, row, provider, requirements, gave_up, past_wait):
    """(outcome, why it stops, packets, provider) of one call to the batch runner. Outcome None: nothing
    moved this time (the lane is shut, or a failed poll, which settles nothing)."""
    review_run_id = row["review_run_id"]
    with (
        claude_approved.carrying(_loads(row, "documents")),
        claude_spend.for_run(review_run_id),
    ):
        provider = provider or rp.claude_for_task(_engine(), step=STEP)
        if provider is None:
            return None, None, None, None
        packets = _PACKETS.get(review_run_id)
        if packets is None:
            packets = _build_packets(
                row["document_id"], row["kind"], row["kind_state"], requirements
            )
            _PACKETS[review_run_id] = packets
        live = {c: p for c, p in packets.items() if c not in gave_up}
        if past_wait:  # read what was sent; nothing new goes out
            sent = _sent_out(conn, _job(review_run_id))
            live = {c: p for c, p in live.items() if c in sent}
        if not live:  # every ask has an end: nothing to send, nothing to wait for
            return None, "", packets, provider
        try:
            outcome = claude_batch_run.run(
                conn,
                provider,
                _job(review_run_id),
                live,
                client=_client(),
                room=_room,
                poll_seconds=0.0,
                max_wait_s=0.0,
                sleep=lambda _s: None,
            )
            return outcome, None, packets, provider
        except claude_spend.StopRun as exc:
            return None, claude_spend.refusal_words(exc, _why_cap()), packets, provider
        except rp.ProviderRefused as exc:
            return None, f"the batch was not accepted ({exc})", packets, provider
        except Exception as exc:  # noqa: BLE001 - a failed poll settles nothing: the next tick reads the batch again
            log.warning("clause review poll: %s", type(exc).__name__)
            return None, None, packets, provider


def _why_stop(outcome, stored, unanswered, packets, provider) -> str | None:
    """With no batch out: None to go on with the next tranche, "" when done, else why what is left stays left."""
    if outcome is None or outcome.waiting:
        return None
    if outcome.over_budget:
        next_worst = claude_batch_run.worst_usd(
            provider.requested_model, packets[outcome.over_budget[0]]
        )
        return None if min(_room()) >= next_worst else _why_cap()
    return None if set(unanswered) - set(stored.unconfirmed) else ""


def _hours() -> float:
    return float(settings.clause_review_batch_wait_hours)


def _past_wait(row, at: float, unanswered, sent, reasons) -> str | None:
    """Past the wait: None while a sent ask can still be read, else why the rest stays left. An ask never sent, and one
    sent and not read, are different things and are worded apart."""
    never = f"it was never sent to Claude within the {_hours():g} h limit (lane shut or stopped first)"
    for custom_id in unanswered:
        if custom_id not in sent:
            reasons[custom_id] = never
    out = [c for c in unanswered if c in sent]
    if not out:
        return ""
    days = float(settings.clause_review_batch_read_days)
    if at >= float(row["started_at"]) + days * 86400.0:
        for custom_id in out:
            reasons[custom_id] = (
                f"it was sent and its result could not be read within {days:g} days; charged "
                "at its worst case because the bill is unknown"
            )
        return ""
    for custom_id in out:
        reasons[custom_id] = (
            f"it was sent and its result was not read within {_hours():g} h (lane shut, a failed poll "
            "or a batch not ended); it stays held and is still read if it can be"
        )
    return None


def tick(review_run_id: str, *, provider=None, now=time.time) -> dict | None:
    """One non-blocking step, inside its run: the caps and the ledger lines are this run's."""
    with claude_spend.for_run(review_run_id):
        return _tick(review_run_id, provider, now)


def _tick(review_run_id: str, provider, now) -> dict | None:
    """Read a batch if it ended, send what fits, write rows, store the honest status."""
    conn = connect()
    ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM clause_review_batches WHERE review_run_id = ?", (review_run_id,)
    ).fetchone()
    if row is None:
        return clause_review.status_of(review_run_id)
    if _run_is_gone(conn, review_run_id):
        return None
    if row["state"] == CLOSED:
        return _reenter_closed(conn, row, provider, now)
    job = _job(review_run_id)
    asks = _loads(row, "asks")
    requirements = _requirements(asks)
    gave_up = _settled(conn, job, set(asks), _loads(row, "gave_up"))
    reasons, written = _loads(row, "reasons"), _written(row)
    at = now()
    past = at >= float(row["deadline_at"])
    pause = (
        LATE_POLL_SECONDS if past else float(settings.clause_review_batch_poll_seconds)
    )
    _save(conn, row, PENDING, gave_up, reasons, written, at + pause)
    outcome, stop, packets, provider = _ask(
        conn, row, provider, requirements, gave_up, past
    )
    stored = claude_batch_run.stored_outcome(conn, job, set(asks))
    gave_up = {**gave_up, **stored.gave_up}
    decided, before = _decided(conn, review_run_id), len(written)
    if not decided:
        for custom_id in _missing_rows(conn, row, written):
            written.pop(
                custom_id
            )  # a re-run comparison took it; its answer is still here
        _write_rows(row, stored.answers, requirements, written)
    unanswered = [
        c
        for c in asks
        if c not in stored.answers and c not in gave_up and c in requirements
    ]
    sent = _sent_out(conn, job)
    for custom_id in unanswered:
        reasons[custom_id] = WHY_WAITING if custom_id in sent else WHY_NOT_YET
    for custom_id in set(stored.answers) - set(written):
        reasons[custom_id] = WHY_DECIDED
    if past and stop is None:
        stop = _past_wait(row, at, unanswered, sent, reasons)
    elif stop is None:
        stop = _why_stop(outcome, stored, unanswered, packets, provider)
    closing = stop is not None
    if closing:
        with claude_spend.for_run(review_run_id):
            _charge_unread(conn, job, row["model"])
    if stop:
        for custom_id in unanswered:
            reasons[custom_id] = stop
    for custom_id in stored.unconfirmed:
        reasons[custom_id] = WHY_UNCONFIRMED
    status = _status(row, written, gave_up, reasons, requirements, not closing, now())
    state = CLOSED if closing else PENDING
    _save(conn, row, state, gave_up, reasons, written, at + pause)
    clause_review._store_status(review_run_id, status)
    if closing:
        _purge(conn, job)
        _PACKETS.pop(review_run_id, None)
        _after_close(review_run_id, rows_added=len(written) > before or not decided)
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
    packets = _build_packets(
        submittal, kind, state, {_custom_id(r["id"]): r for r in wanted}
    )
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
