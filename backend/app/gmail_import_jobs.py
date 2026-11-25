"""The mailbox import runs as a BACKGROUND JOB, never inside the web request (owner's test of 26 Nov 2026: "Activate label" imported every labelled mail inside
the request and only then set the mailbox active, so a long import, a timeout or a restart left it "waiting for a dedicated label" for ever).

Activation now saves the label and sets the mailbox ACTIVE first, in one short request, and queues an import job. One job runs at a time on its own thread: it
lists the label's messages and imports them ONE AT A TIME, each in its own transaction, saving progress ("imported N of M") as it goes. A message that fails
is counted and named by its subject and NEVER stops the rest. A job left running by a stopped server goes back to the queue (the import is safe to run
again: a message already imported is a duplicate and counts as done). "Check now" queues one poll (the failed messages of the last import are tried once more,
then the history since the last check). The poller skips a mailbox while its import runs. Everything is written under the data folder; nothing is written
into the code folder, so a development server that reloads on file changes is not triggered.
"""

from __future__ import annotations

import logging
import threading
import uuid

import httpx

from . import technical_queries
from .db import connect

log = logging.getLogger(__name__)

AUTO_START = True  # False in tests: a job is run by hand (`run_job`)
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()
MAX_NAMED = 50


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


def enqueue(mailbox_id: str, kind: str, label_id: str | None = None) -> str:
    """Queue a job ("import" of the label, or one "poll"); the active job of the mailbox is returned instead of a second one."""
    with connect() as conn:
        create_tables(conn)
        active = conn.execute(
            "SELECT id FROM gmail_import_jobs WHERE mailbox_id=? AND state IN ('queued','running') ORDER BY created_at LIMIT 1",
            (mailbox_id,),
        ).fetchone()
        if active:
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
        "SELECT id,kind,state,total,done,failed,error,created_at,updated_at FROM gmail_import_jobs WHERE mailbox_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (mailbox_id,),
    ).fetchone()
    if row is None:
        return None
    job = dict(row)
    job["failures"] = [
        {"subject": r["subject"] or "(no subject)", "reason": r["reason"]}
        for r in conn.execute(
            "SELECT subject, reason FROM gmail_import_failures WHERE job_id=? LIMIT ?",
            (job["id"], MAX_NAMED),
        )
    ]
    return job


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
                f"the message could not be imported ({type(exc).__name__})",
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
    if job is None or box is None:
        return
    _set(job_id, state="running")
    try:
        client = client or _client(box["id"])
        admin_role = None
        if settings.auth_mode != access.AUTH_DISABLED:
            admin_role, held = access.upload_admin_role(box["owner_user_id"])
            if not held:
                raise PermissionError(
                    "the mailbox owner must hold the administrator role"
                )
        if job["kind"] == "poll":
            _poll(job_id, client, box, admin_role)
        else:
            _import(job_id, client, box, job["label_id"] or box["label_id"], admin_role)
    except Exception as exc:  # noqa: BLE001 - the job says it failed (by type, never the text); the mailbox stays active
        log.warning("gmail import job failed (%s)", type(exc).__name__)
        _set(
            job_id,
            state="failed",
            error=f"the mailbox could not be read ({type(exc).__name__}); use Check now to try again",
        )
        return
    _checked(box["id"])
    _set(job_id, state="done")


def _import_one(
    job_id, client, box, label_id, admin_role, message_id, progress_failed
) -> bool:
    """One message, in its own transaction(s); returns True when imported (or already imported), False when it failed (counted and named)."""
    from . import gmail_worker

    subject = None
    try:
        message = client.message(message_id)
        subject = message.subject
        gmail_worker._process_message(
            client, message_id, mailbox_id=box["id"], actor_user_id=box["owner_user_id"], admin_role=admin_role,
            label_id=label_id, mailbox_address=box["email"], message=message,
        )  # fmt: skip
        return True
    except Exception as exc:  # noqa: BLE001 - counted, named by subject, and never stops the rest
        log.warning("gmail import: a message failed (%s)", type(exc).__name__)
        _fail(job_id, message_id, subject, exc)
        progress_failed()
        return False


def _import(job_id, client, box, label_id, admin_role) -> None:
    ids = client.list_message_ids(label_id)
    _set(job_id, total=len(ids))
    done = failed = 0
    for message_id in ids:
        if _stop.is_set():
            raise RuntimeError("stopped")
        ok = _import_one(
            job_id, client, box, label_id, admin_role, message_id, lambda: None
        )
        done += 1 if ok else 0
        failed += 0 if ok else 1
        _set(job_id, done=done, failed=failed)
        _checked(box["id"])


def _poll(job_id, client, box, admin_role) -> None:
    """One poll: the failed messages of the last import are tried once more, then the history since the last check."""
    from . import gmail_worker

    with connect() as conn:
        again = [r["provider_message_id"] for r in conn.execute(
            "SELECT f.provider_message_id FROM gmail_import_failures f JOIN gmail_import_jobs j ON j.id=f.job_id WHERE j.mailbox_id=?", (box["id"],))]  # fmt: skip
    _set(job_id, total=len(again))
    done = failed = 0
    for message_id in again:
        ok = _import_one(
            job_id, client, box, box["label_id"], admin_role, message_id, lambda: None
        )
        done += 1 if ok else 0
        failed += 0 if ok else 1
        _set(job_id, done=done, failed=failed)
        if ok:
            with connect() as conn:  # imported now: no longer a failure to retry
                conn.execute("DELETE FROM gmail_import_failures WHERE provider_message_id=? AND job_id IN (SELECT id FROM gmail_import_jobs WHERE mailbox_id=?)", (message_id, box["id"]))  # fmt: skip
    if box["label_id"] and box["connection_state"] == "active":
        try:
            gmail_worker.poll_mailbox(client, box["id"], box["owner_user_id"])
        except httpx.HTTPError:
            raise


def _loop() -> None:
    while not _stop.is_set():
        with connect() as conn:
            create_tables(conn)
            nxt = conn.execute(
                "SELECT id FROM gmail_import_jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
        if nxt is None:
            _wake.wait(30)
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
