"""Background polling for connected Gmail technical-query mailboxes."""

from __future__ import annotations

import logging
import threading

import httpx

from . import gmail_auth
from .db import connect
from .gmail_client import GmailApiClient
from .gmail_worker import poll_mailbox
from .technical_queries import enabled, now

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()
_log = logging.getLogger(__name__)


_failed_last = False


def run_once() -> int:
    global _failed_last
    _failed_last = False
    if not enabled():  # the way-back switch: no mailbox is polled, no socket opened
        return 0
    with connect() as conn:
        mailboxes = conn.execute(
            "SELECT id,owner_user_id FROM gmail_mailboxes WHERE connection_state='active'"
        ).fetchall()
    processed = 0
    for mailbox in mailboxes:
        try:
            token = gmail_auth.access_token(mailbox["id"])
            processed += len(
                poll_mailbox(
                    GmailApiClient(token), mailbox["id"], mailbox["owner_user_id"]
                )
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                with connect() as conn:
                    conn.execute(
                        "UPDATE gmail_mailboxes SET connection_state='revoked',updated_at=? WHERE id=?",
                        (now(), mailbox["id"]),
                    )
            _failed_last = True
            _log.warning(
                "technical-query mailbox sync failed: HTTP %s", exc.response.status_code
            )
        except Exception as exc:  # noqa: BLE001 - one mailbox failure must not stop the others
            # Never log tokens, message bodies, addresses or provider response text.
            _failed_last = True
            _log.warning("technical-query mailbox sync failed: %s", type(exc).__name__)
    return processed


POLL_SECONDS = 60
MAX_WAIT_SECONDS = 900
_failures = 0


def wait_seconds(failures: int) -> int:
    """One minute while things work; doubling to at most 15 minutes while Google or the network keeps failing."""
    return min(POLL_SECONDS * (2 ** max(0, failures)), MAX_WAIT_SECONDS)


def _loop() -> None:
    global _failures
    while not _stop.is_set():
        run_once()
        _failures = _failures + 1 if _failed_last else 0
        _stop.wait(wait_seconds(_failures))


def start() -> None:
    global _thread
    if not enabled():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        with connect() as conn:
            has_mailbox = conn.execute(
                "SELECT 1 FROM gmail_mailboxes WHERE connection_state='active' LIMIT 1"
            ).fetchone()
        if not has_mailbox:
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, daemon=True, name="technical-query-gmail-sync"
        )
        _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    with _lock:
        thread = _thread
        _thread = None
    if thread is not None:
        thread.join(timeout=2)
