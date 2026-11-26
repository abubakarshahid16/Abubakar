"""The mailbox import runs as a BACKGROUND JOB, never inside the web request (owner's test of 26 Nov 2026: "Activate label" imported every labelled mail inside
the request and only then set the mailbox active, so a long import, a timeout or a restart left it "waiting for a dedicated label" for ever).

Activation now saves the label and sets the mailbox ACTIVE first, in one short request, and queues an import job. One job runs at a time on its own thread: it
lists the label's messages and imports them ONE AT A TIME, each in its own transaction, saving progress ("imported N of M") as it goes. A message that fails
is counted and named by its subject and NEVER stops the rest. A job is never lost: a server stop (every live update restarts the server) leaves it QUEUED,
a job left running by a killed server goes back to the queue, and when Gmail cannot be reached (at the start or in the middle) the job goes back to the queue with
a growing wait and the messages it did not reach wait for it (they are never all marked failed); the import is safe to run again: a message already imported
is a duplicate and counts as done. "Check now" runs a waiting job at once, queues the import again when the last import ended failed, else queues one poll
(the failed messages of the last import are tried once more, then the history since the last check). The poller does the same on its own (a failed import
is queued again; failed messages are tried again every 15 minutes) and skips a mailbox while its job runs. Everything is written under the data folder; nothing is written
into the code folder, so a development server that reloads on file changes is not triggered.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid

import httpx

from . import technical_queries
from .db import connect
from .technical_query_replies import ALREADY, NO_QUERY

log = logging.getLogger(__name__)

AUTO_START = True  # False in tests: a job is run by hand (`run_job`)
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()
MAX_NAMED = 50
#: Seconds a job waits after Gmail could not be reached, by attempt (the last one repeats); after MAX_ATTEMPTS the job is failed and "Check now" starts it again.
BACKOFF_SECONDS = (60, 120, 300, 600, 900)
MAX_ATTEMPTS = 8
RETRY_FAILED_MESSAGES_SECONDS = 900
#: Failed jobs since the last good one after which the poller stops queueing the mailbox's work again by itself and marks the mailbox "in error".
MAX_AUTO_REQUEUES = 3
GONE_SENTENCE = "This mailbox is no longer connected, so its import was stopped."
ADMIN_SENTENCE = "The person who connected this mailbox no longer holds the administrator role, so Gmail is not read. An administrator can connect it again."
REVOKED_SENTENCE = "Google no longer allows this app to read the mailbox. Connect it again."
GIVEN_UP_SENTENCE = "Gmail could not be read after several tries, so the checking stopped. Use Check now when Gmail is back, or connect the mailbox again."
WAITING_SENTENCE = "Gmail could not be read just now. It will try again by itself, or use Check now."
FAILED_SENTENCE = "Gmail could not be read just now. Use Check now to try again."


class Interrupted(Exception):
    """The server is stopping: the job stays queued and goes on when the server is back."""


def _outage(exc: Exception) -> bool:
    """Gmail or the network could not answer (a transport fault, a timeout, a server error, a refused token, a rate limit): not the message's fault."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in (401, 403, 429) or code >= 500
    return False


def create_tables(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS gmail_import_jobs (id TEXT PRIMARY KEY, mailbox_id TEXT NOT NULL, kind TEXT NOT NULL, label_id TEXT, "
        "state TEXT NOT NULL, total INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, "
        "error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS gmail_import_failures (job_id TEXT NOT NULL, provider_message_id TEXT NOT NULL, subject TEXT, reason TEXT NOT NULL, "
        "PRIMARY KEY (job_id, provider_message_id))"
    )
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(gmail_mailboxes)")}
    if columns and "last_checked_at" not in columns:
        conn.execute("ALTER TABLE gmail_mailboxes ADD COLUMN last_checked_at TEXT")
    if columns and "status_note" not in columns:
        conn.execute("ALTER TABLE gmail_mailboxes ADD COLUMN status_note TEXT")  # why a mailbox is in error or revoked, in one plain sentence
    job_columns = {r["name"] for r in conn.execute("PRAGMA table_info(gmail_import_jobs)")}
    if "retry_at" not in job_columns:
        conn.execute("ALTER TABLE gmail_import_jobs ADD COLUMN retry_at TEXT")
    if "attempts" not in job_columns:
        conn.execute("ALTER TABLE gmail_import_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    # {reason: count} of listed messages that were not imported (`gmail_worker.skip_reason`)
    if "skipped_json" not in job_columns:
        conn.execute("ALTER TABLE gmail_import_jobs ADD COLUMN skipped_json TEXT")


def enqueue(mailbox_id: str, kind: str, label_id: str | None = None, *, run_now: bool = False) -> str:
    """Queue a job ("import" of the label, or one "poll"); the active job of the mailbox is returned instead of a second one
    (`run_now`: a job waiting for its next try is made ready at once)."""
    with connect() as conn:
        create_tables(conn)
        active = conn.execute(
            "SELECT id FROM gmail_import_jobs WHERE mailbox_id=? AND state IN ('queued','running') ORDER BY created_at LIMIT 1",
            (mailbox_id,),
        ).fetchone()
        if active:
            if run_now:
                conn.execute("UPDATE gmail_import_jobs SET retry_at=NULL WHERE id=? AND state='queued'", (active["id"],))
                _wake.set()
                if AUTO_START:
                    start()
            return active["id"]
        job_id, at = str(uuid.uuid4()), technical_queries.now()
        conn.execute(
            "INSERT INTO gmail_import_jobs(id,mailbox_id,kind,label_id,state,created_at,updated_at) VALUES (?,?,?,?,'queued',?,?)",
            (job_id, mailbox_id, kind, label_id, at, at),
        )
    _wake.set()
    if AUTO_START:
        start()
    return job_id


def active(conn, mailbox_id: str) -> bool:
    """True while an import or poll job of the mailbox is queued or running (the poller leaves such a mailbox alone). Reads only."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gmail_import_jobs'"
        ).fetchone()
        is None
    ):
        return False
    return (
        conn.execute(
            "SELECT 1 FROM gmail_import_jobs WHERE mailbox_id=? AND state IN ('queued','running')",
            (mailbox_id,),
        ).fetchone()
        is not None
    )


def latest(conn, mailbox_id: str) -> dict | None:
    """The newest job of the mailbox with the failed messages named by subject (at most MAX_NAMED). Reads only."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gmail_import_jobs'"
        ).fetchone()
        is None
    ):
        return None
    row = conn.execute(
        "SELECT * FROM gmail_import_jobs WHERE mailbox_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (mailbox_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("id", "kind", "state", "total", "done", "failed", "error", "created_at")
    job = {k: row[k] for k in (*keys, "updated_at")}
    columns = row.keys()
    try:
        stored = row["skipped_json"] if "skipped_json" in columns else None
        job["skipped"] = json.loads(stored or "{}")
    except ValueError:
        stored, job["skipped"] = None, {}
    # an import that ran before the reasons were counted: its "done" is not "imported"; the page says what is stored instead
    job["reasons_recorded"] = stored is not None
    # "imported" counts only messages imported (or already held): a listed message that is not one to import is said apart
    job["imported"] = max(0, (job["done"] or 0) - sum(job["skipped"].values()))
    # the queries this mailbox's messages are in now ("77 messages in 33 queries": replies and forwards join one query)
    held = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_messages'"
    ).fetchone()
    counted = (
        conn.execute(
            "SELECT COUNT(DISTINCT query_id), COUNT(*) FROM query_messages WHERE mailbox_id=?",
            (mailbox_id,),
        ).fetchone()
        if held
        else (None, None)
    )
    job["queries"], job["messages"] = counted[0], counted[1]
    job["failures"] = [
        {"subject": r["subject"] or "(no subject)", "reason": r["reason"]}
        for r in conn.execute(
            "SELECT subject, reason FROM gmail_import_failures WHERE job_id=? LIMIT ?",
            (job["id"], MAX_NAMED),
        )
    ]
    return job


def stop_mailbox(mailbox_id: str, state: str, note: str) -> None:
    """A fault that does not clear by waiting: the mailbox is marked `state` ("error" or "revoked") with one plain sentence for the screen, the poller leaves it
    alone, and its queued jobs are failed with that sentence (so no thread spins on them). A person's Check now (error) or a new connection (revoked) starts it again."""
    with connect() as conn:
        create_tables(conn)
        conn.execute(
            "UPDATE gmail_mailboxes SET connection_state=?, status_note=?, updated_at=? WHERE id=?", (state, note, technical_queries.now(), mailbox_id)
        )
        conn.execute(
            "UPDATE gmail_import_jobs SET state='failed', error=?, retry_at=NULL, updated_at=? WHERE mailbox_id=? AND state='queued'",
            (note, technical_queries.now(), mailbox_id),
        )


def check_now(mailbox_id: str) -> str:
    """"Check now": a job waiting for its next try runs at once; else, when the last IMPORT of the mailbox ended failed, the import is queued again (the label
    mail it never reached is not lost); else one poll is queued. Returns the job id."""
    with connect() as conn:
        create_tables(conn)
        # a mailbox in error (Gmail was unreachable for too long, or the owner lost the role) tries again when a person asks
        conn.execute(
            "UPDATE gmail_mailboxes SET connection_state='active', status_note=NULL, updated_at=? WHERE id=? AND connection_state='error'",
            (technical_queries.now(), mailbox_id),
        )
        box = conn.execute("SELECT label_id FROM gmail_mailboxes WHERE id=?", (mailbox_id,)).fetchone()
        last = conn.execute(
            "SELECT state FROM gmail_import_jobs WHERE mailbox_id=? AND kind='import' ORDER BY created_at DESC, rowid DESC LIMIT 1", (mailbox_id,)
        ).fetchone()
    if last is not None and last["state"] == "failed" and box is not None and box["label_id"]:
        return enqueue(mailbox_id, "import", box["label_id"], run_now=True)
    return enqueue(mailbox_id, "poll", run_now=True)


def resume_due(mailbox_id: str) -> bool:
    """For the poller, on its own: queue what a person would press "Check now" for. True when a job was queued (the poller then leaves the mailbox to it)."""
    with connect() as conn:
        create_tables(conn)
        box = conn.execute("SELECT label_id FROM gmail_mailboxes WHERE id=?", (mailbox_id,)).fetchone()
        last = conn.execute(
            "SELECT state FROM gmail_import_jobs WHERE mailbox_id=? AND kind='import' ORDER BY created_at DESC, rowid DESC LIMIT 1", (mailbox_id,)
        ).fetchone()
        stale = conn.execute(
            "SELECT 1 FROM gmail_import_failures f JOIN gmail_import_jobs j ON j.id=f.job_id WHERE j.mailbox_id=? LIMIT 1", (mailbox_id,)
        ).fetchone()
        newest = conn.execute("SELECT MAX(updated_at) m FROM gmail_import_jobs WHERE mailbox_id=?", (mailbox_id,)).fetchone()["m"]
        failed_run = conn.execute(
            "SELECT COUNT(*) c FROM gmail_import_jobs WHERE mailbox_id=? AND state='failed' AND created_at > COALESCE("
            "(SELECT MAX(created_at) FROM gmail_import_jobs WHERE mailbox_id=? AND state='done'), '')",
            (mailbox_id, mailbox_id),
        ).fetchone()["c"]
    if failed_run >= MAX_AUTO_REQUEUES:  # a fault that never clears is not retried for ever: the mailbox is marked, a person decides
        stop_mailbox(mailbox_id, "error", GIVEN_UP_SENTENCE)
        return False
    if last is not None and last["state"] == "failed" and box is not None and box["label_id"]:
        enqueue(mailbox_id, "import", box["label_id"])
        return True
    if stale is not None and (newest is None or newest <= _ago(RETRY_FAILED_MESSAGES_SECONDS)):
        enqueue(mailbox_id, "poll")
        return True
    return False


def _ago(seconds: int) -> str:
    return _later_than(-seconds)


def _later_than(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set(job_id: str, **fields) -> None:
    sets = ",".join(f"{k}=?" for k in fields) + ",updated_at=?"
    with connect() as conn:
        conn.execute(
            f"UPDATE gmail_import_jobs SET {sets} WHERE id=?",
            (*fields.values(), technical_queries.now(), job_id),
        )


def _checked(mailbox_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE gmail_mailboxes SET last_checked_at=? WHERE id=?",
            (technical_queries.now(), mailbox_id),
        )


def _fail(job_id: str, message_id: str, subject: str | None, exc: Exception) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gmail_import_failures(job_id,provider_message_id,subject,reason) VALUES (?,?,?,?)",
            (
                job_id,
                message_id,
                (subject or "")[:200] or None,
                "this message could not be read, so it was skipped",
            ),
        )


def _client(mailbox_id: str):
    from . import gmail_auth
    from .gmail_client import GmailApiClient

    return GmailApiClient(gmail_auth.access_token(mailbox_id))


def run_job(job_id: str, *, client=None) -> None:
    """Do one job to its end (state done or failed). `client` is injected by tests; the thread builds the real one. Never raises."""
    from . import access
    from .config import settings

    with connect() as conn:
        create_tables(conn)
        job = conn.execute(
            "SELECT * FROM gmail_import_jobs WHERE id=?", (job_id,)
        ).fetchone()
        box = (
            conn.execute(
                "SELECT * FROM gmail_mailboxes WHERE id=?", (job["mailbox_id"],)
            ).fetchone()
            if job
            else None
        )
    if job is None:
        return
    if box is None:  # its mailbox row is gone: the job says so and ends, it never stays queued for the thread to pick again
        _set(job_id, state="failed", error=GONE_SENTENCE, retry_at=None)
        return
    if box["connection_state"] in ("revoked", "error"):
        _set(job_id, state="failed", error=box["status_note"] if "status_note" in box.keys() and box["status_note"] else GIVEN_UP_SENTENCE, retry_at=None)
        return
    _set(job_id, state="running", retry_at=None, error=None)
    try:
        client = client or _client(box["id"])
        admin_role = None
        if settings.auth_mode != access.AUTH_DISABLED:
            admin_role, held = access.upload_admin_role(box["owner_user_id"])
            if not held:
                raise PermissionError("the mailbox owner must hold the administrator role")
        if job["kind"] == "poll":
            _poll(job_id, client, box, admin_role)
        else:
            _import(job_id, client, box, job["label_id"] or box["label_id"], admin_role)
    except Interrupted:  # the server is stopping: the job stays queued, nothing is lost, no try is counted
        _set(job_id, state="queued")
        return
    except PermissionError:  # not a Gmail fault: waiting would not help; the mailbox is marked and the screen says why
        log.warning("gmail import job failed (PermissionError)")
        _set(job_id, state="failed", error=ADMIN_SENTENCE)
        stop_mailbox(box["id"], "error", ADMIN_SENTENCE)
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:  # not a refused token: Gmail could not be read, the ordinary way
            log.warning("gmail import job will be tried again (HTTPStatusError)")
            _try_again_later(job_id, int(job["attempts"] or 0), box["id"])
            return
        log.warning("gmail import job failed: the token was refused")  # Google withdrew its consent
        _set(job_id, state="failed", error=REVOKED_SENTENCE)
        stop_mailbox(box["id"], "revoked", REVOKED_SENTENCE)
        return
    except Exception as exc:  # noqa: BLE001 - Gmail could not be reached, at the start or in the middle: back to the queue with a growing wait (by type, never the text)
        log.warning("gmail import job will be tried again (%s)", type(exc).__name__)
        _try_again_later(job_id, int(job["attempts"] or 0), box["id"])
        return
    _checked(box["id"])
    _set(job_id, state="done")


def _try_again_later(job_id: str, tried: int, mailbox_id: str) -> None:
    """Back to the queue after the wait for this attempt; after MAX_ATTEMPTS it is failed and "Check now" starts it again."""
    attempts = tried + 1
    if attempts >= MAX_ATTEMPTS:
        _set(job_id, state="failed", error=GIVEN_UP_SENTENCE, attempts=attempts, retry_at=None)
        stop_mailbox(mailbox_id, "error", GIVEN_UP_SENTENCE)  # the last try is used: no automatic retry goes on for ever
        return
    wait = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
    _set(job_id, state="queued", error=WAITING_SENTENCE, attempts=attempts, retry_at=_later_than(wait))


def _import_one(
    job_id, client, box, label_id, admin_role, message_id, progress_failed, known_subject=None
) -> bool:
    """One message, in its own transaction(s); returns True when imported (or already imported), the reason (`gmail_worker.skip_reason`) when it is
    not one to import, False when it failed (counted and named)."""
    from . import gmail_worker

    subject = known_subject
    try:
        message = client.message(message_id)
        subject = message.subject
        skipped = gmail_worker.skip_reason(message, label_id, box["email"])
        # listed but not one to import: counted with its reason, never as imported
        if skipped and skipped != gmail_worker.OWN_MAIL:
            return skipped
        kept = gmail_worker._process_message(
            client, message_id, mailbox_id=box["id"], actor_user_id=box["owner_user_id"], admin_role=admin_role,
            label_id=label_id, mailbox_address=box["email"], message=message,
        )  # fmt: skip
        # our own reply: its reason (kept with its query, or no query of it yet), never counted as imported
        if (kept or {}).get("own_reply"):
            return kept["own_reply"]
        # read again ("Import the label again"): a message already stored adds nothing and is said apart
        return ALREADY if (kept or {}).get("duplicate") else True
    except Exception as exc:  # noqa: BLE001 - counted, named by subject, and never stops the rest
        if _outage(exc):  # Gmail, not the message: the job waits and goes on with the messages it did not reach
            raise
        log.warning("gmail import: a message failed (%s)", type(exc).__name__)
        _fail(job_id, message_id, subject, exc)
        progress_failed()
        return False


def _import(job_id, client, box, label_id, admin_role) -> None:
    ids = client.list_message_ids(label_id)
    # the reasons are counted from the start
    _set(job_id, total=len(ids), skipped_json="{}")
    done = failed = 0
    skipped: dict[str, int] = {}
    # our own replies read before the message they answer: tried again at the end
    later: list[str] = []
    for pass_ids, last in ((ids, False), (later, True)):
        for message_id in list(pass_ids):
            if _stop.is_set():
                raise Interrupted()
            ok = _import_one(
                job_id, client, box, label_id, admin_role, message_id, lambda: None
            )
            if ok == NO_QUERY and not last:
                later.append(message_id)
                continue
            if isinstance(ok, str):
                skipped[ok] = skipped.get(ok, 0) + 1
            done += 1 if ok else 0
            failed += 0 if ok else 1
            _set(job_id, done=done, failed=failed, skipped_json=json.dumps(skipped))
            _checked(box["id"])


def _poll(job_id, client, box, admin_role) -> None:
    """One poll: the failed messages of the last import are tried once more, then the history since the last check."""
    from . import gmail_worker

    with connect() as conn:
        again: dict[str, str | None] = {}
        for r in conn.execute(
            "SELECT f.provider_message_id, f.subject FROM gmail_import_failures f JOIN gmail_import_jobs j ON j.id=f.job_id WHERE j.mailbox_id=? ORDER BY j.created_at", (box["id"],)):  # fmt: skip
            again[r["provider_message_id"]] = r["subject"] or again.get(r["provider_message_id"])  # a later row with no subject never hides the name
    _set(job_id, total=len(again))
    done = failed = 0
    for message_id, known_subject in again.items():
        if _stop.is_set():
            raise Interrupted()
        ok = _import_one(
            job_id, client, box, box["label_id"], admin_role, message_id, lambda: None, known_subject
        )
        done += 1 if ok else 0
        failed += 0 if ok else 1
        _set(job_id, done=done, failed=failed)
        if ok:
            with connect() as conn:  # imported now: no longer a failure to retry
                conn.execute("DELETE FROM gmail_import_failures WHERE provider_message_id=? AND job_id IN (SELECT id FROM gmail_import_jobs WHERE mailbox_id=?)", (message_id, box["id"]))  # fmt: skip
    if box["label_id"] and box["connection_state"] == "active":
        gmail_worker.poll_mailbox(client, box["id"], box["owner_user_id"])


def _loop() -> None:
    while not _stop.is_set():
        with connect() as conn:
            create_tables(conn)
            nxt = conn.execute(
                "SELECT id FROM gmail_import_jobs WHERE state='queued' AND (retry_at IS NULL OR retry_at<=?) ORDER BY created_at LIMIT 1",
                (_later_than(0),),
            ).fetchone()
        if nxt is None:
            _wake.wait(15)
            _wake.clear()
            continue
        run_job(nxt["id"])


def start() -> None:
    """Start the one job thread (idempotent). Only while the feature is switched on."""
    global _thread
    if not technical_queries.enabled():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="gmail-import")
        _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    with _lock:
        thread, _thread = _thread, None
    if thread is not None:
        thread.join(timeout=2)


def recover_interrupted() -> int:
    """At server start: a job left running by a stopped server goes back to the queue (an import is safe to run again)."""
    with connect() as conn:
        create_tables(conn)
        return int(
            conn.execute(
                "UPDATE gmail_import_jobs SET state='queued', updated_at=? WHERE state='running'",
                (technical_queries.now(),),
            ).rowcount
            or 0
        )
