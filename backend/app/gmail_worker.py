"""Retry-safe Gmail notification worker boundary."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from email.utils import parseaddr
from io import BytesIO
from typing import Any

import httpx

from . import access, attachment_safety
from . import upload as upload_mod
from .config import settings
from .db import connect
from .gmail_client import GmailApiClient
from .technical_queries import (
    import_message,
    link_attachment,
    mark_filed,
    now,
    unfiled_attachment_ids,
)

log = logging.getLogger(__name__)


def _store_raw_email(raw: bytes) -> tuple[str, str]:
    if not raw or len(raw) > 50_000_000:
        raise ValueError("the original email is empty or too large")
    digest = hashlib.sha256(raw).hexdigest()
    folder = settings.data_dir / "technical_query_mail"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    path = folder / f"{digest}.eml"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return digest, str(path)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
    return digest, str(path)


def _process_message(
    client: GmailApiClient,
    message_id: str,
    *,
    mailbox_id: str,
    actor_user_id: str,
    admin_role,
    label_id: str | None,
    mailbox_address: str | None,
) -> dict[str, Any] | None:
    """Import one message with its PDF attachments. None when it is not one to import (another label, or the mailbox's own mail)."""
    message = client.message(message_id)
    if label_id and label_id not in message.label_ids:
        return None
    if (
        mailbox_address
        and parseaddr(message.from_address)[1].casefold() == mailbox_address.casefold()
    ):
        return None
    raw_hash, raw_ref = _store_raw_email(client.raw_message(message_id))
    item, duplicate = import_message(
        {
            "provider": "gmail",
            "mailbox_id": mailbox_id,
            "provider_message_id": message.provider_message_id,
            "provider_thread_id": message.thread_id,
            "from_address": message.from_address,
            "to_addresses": message.to_addresses,
            "cc_addresses": message.cc_addresses,
            "subject": message.subject,
            "body": message.body,
            "received_at": message.received_at,
            "raw_message_hash": raw_hash,
            "raw_storage_ref": raw_ref,
            "attachments": message.attachments,
        },
        actor_user_id,
        False,
        settings.auth_mode == access.AUTH_DISABLED,
    )
    stored_message = next(
        row
        for row in item["messages"]
        if row["provider_message_id"] == message.provider_message_id
    )
    for source, stored in zip(
        message.attachments, stored_message["attachments"], strict=True
    ):
        if stored["document_id"] or not source["filename"].lower().endswith(".pdf"):
            continue
        if source.get("attachment_id"):
            content = client.attachment(
                message.provider_message_id, source["attachment_id"]
            )
        elif source.get("inline_data"):
            encoded = source["inline_data"]
            content = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        else:
            continue
        if source["size_bytes"] and len(content) != source["size_bytes"]:
            raise ValueError("the Gmail attachment size did not match its metadata")
        checked = attachment_safety.check_before_library(content)
        if (
            checked["status"] != attachment_safety.CLEAN
        ):  # flagged or unreadable: it never enters the library
            with connect() as conn:
                conn.execute(
                    "UPDATE query_attachments SET scan_status=?,scan_detail=? WHERE id=?",
                    (
                        checked["status"],
                        ", ".join(checked["findings"]) or None,
                        stored["id"],
                    ),
                )
            continue
        with connect() as conn:
            flagged_before = unfiled_attachment_ids(conn)
        row, _, duplicate_of = upload_mod.ingest(BytesIO(content), source["filename"])
        if duplicate_of is not None and settings.auth_mode != access.AUTH_DISABLED:
            if not access.scope_for_user(actor_user_id).may_read_attachment(row["id"]):
                raise PermissionError(
                    "the duplicate attachment document is not readable"
                )
        elif admin_role is not None:
            access.grant_uploaded_document_to_admin(
                row["id"], admin_role, actor_user_id
            )
        item = (
            link_attachment(
                item["id"],
                stored["id"],
                row["id"],
                actor_user_id,
                actor_user_id,
                False,
                settings.auth_mode == access.AUTH_DISABLED,
            )
            or item
        )
        if duplicate_of is not None and row["id"] not in flagged_before:
            with connect() as conn:  # a paper the library already held is not hidden by being attached to a query
                mark_filed(conn, row["id"], actor_user_id)
    return {"query_id": item.get("id"), "duplicate": duplicate}


MAX_TRIES = 3


def is_transient(exc: BaseException) -> bool:
    """A failure that says nothing about the message: the network, a Google 429 or a Google 5xx. Retried later (with a longer wait), never counted."""
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500)


def _note_failure(mailbox_id: str, message_id: str, exc: Exception) -> int:
    """Count one failed import of this message and say why in plain words (the exception type only, never its text). Returns the tries."""
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gmail_failed_messages(mailbox_id TEXT NOT NULL, provider_message_id TEXT NOT NULL, tries INTEGER NOT NULL, "
            "reason TEXT NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(mailbox_id, provider_message_id))"
        )
        row = conn.execute(
            "SELECT tries FROM gmail_failed_messages WHERE mailbox_id=? AND provider_message_id=?",
            (mailbox_id, message_id),
        ).fetchone()
        tries = (row["tries"] if row else 0) + 1
        state = "failed" if tries >= MAX_TRIES else "retrying"
        conn.execute(
            "INSERT OR REPLACE INTO gmail_failed_messages(mailbox_id,provider_message_id,tries,reason,state,updated_at) VALUES (?,?,?,?,?,?)",
            (
                mailbox_id,
                message_id,
                tries,
                f"the message could not be imported ({type(exc).__name__})",
                state,
                now(),
            ),
        )
    return tries


def process_history(
    client: GmailApiClient,
    history_id: str,
    actor_user_id: str,
    *,
    mailbox_id: str,
    message_ids: list[str] | None = None,
    label_id: str | None = None,
    mailbox_address: str | None = None,
) -> list[dict[str, Any]]:
    if not actor_user_id or not mailbox_id:
        raise ValueError("a mailbox owner and mailbox identity are required")
    admin_role = None
    if settings.auth_mode != access.AUTH_DISABLED:
        admin_role, held = access.upload_admin_role(actor_user_id)
        if not held:
            raise PermissionError("the mailbox owner must hold the administrator role")
    results = []
    for message_id in (
        message_ids if message_ids is not None else client.history(history_id, label_id)
    ):
        try:
            result = _process_message(
                client,
                message_id,
                mailbox_id=mailbox_id,
                actor_user_id=actor_user_id,
                admin_role=admin_role,
                label_id=label_id,
                mailbox_address=mailbox_address,
            )
        except Exception as exc:  # noqa: BLE001 - one bad message is counted, marked and, after MAX_TRIES, stepped over; never logged by text
            log.warning("gmail import: a message failed (%s)", type(exc).__name__)
            if is_transient(exc):
                raise  # an outage, a refusal to answer now (429) or a Google fault (5xx): the message is fine, so it is not counted as bad
            if _note_failure(mailbox_id, message_id, exc) < MAX_TRIES:
                raise  # the cursor stays: it is tried again at the next poll
            continue
        if result is not None:
            results.append(result)
    return results


def poll_mailbox(
    client: GmailApiClient, mailbox_id: str, actor_user_id: str
) -> list[dict[str, Any]]:
    """Advance the cursor only after every changed message is persisted."""
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT owner_user_id,email,last_history_id,label_id,connection_state FROM gmail_mailboxes WHERE id=?",
            (mailbox_id,),
        ).fetchone()
    if (
        mailbox is None
        or mailbox["owner_user_id"] != actor_user_id
        or mailbox["connection_state"] != "active"
        or not mailbox["label_id"]
    ):
        raise PermissionError("mailbox is not active for this user")
    old_cursor = mailbox["last_history_id"]
    try:
        message_ids, next_cursor = client.history_delta(old_cursor, mailbox["label_id"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        # Gmail expires history cursors. Capture a new cursor before listing
        # current labelled mail so arrivals during the full scan are replayed.
        next_cursor = str(client.profile().get("historyId") or "")
        if not next_cursor:
            raise RuntimeError("Gmail did not return a recovery cursor") from exc
        message_ids = client.list_message_ids(mailbox["label_id"])
    results = process_history(
        client,
        old_cursor,
        actor_user_id,
        mailbox_id=mailbox_id,
        message_ids=message_ids,
        label_id=mailbox["label_id"],
        mailbox_address=mailbox["email"],
    )
    with connect() as conn:
        updated = conn.execute(
            "UPDATE gmail_mailboxes SET last_history_id=?,updated_at=? WHERE id=? AND last_history_id=? AND connection_state='active'",
            (next_cursor, now(), mailbox_id, old_cursor),
        )
        if updated.rowcount != 1:
            raise RuntimeError("mailbox cursor changed during processing; retry safely")
    return results


def activate_label(
    client: GmailApiClient, mailbox_id: str, actor_user_id: str, label_id: str
) -> list[dict[str, Any]]:
    """Import the selected label once, then enable incremental polling."""
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT owner_user_id,email,last_history_id,connection_state FROM gmail_mailboxes WHERE id=?",
            (mailbox_id,),
        ).fetchone()
    if (
        mailbox is None
        or mailbox["owner_user_id"] != actor_user_id
        or mailbox["connection_state"] != "needs_label"
    ):
        raise PermissionError("mailbox is not awaiting label selection")
    if label_id not in {label.get("id") for label in client.labels()}:
        raise ValueError("select a user-created Gmail label")
    ids = client.list_message_ids(label_id)
    results = process_history(
        client,
        mailbox["last_history_id"],
        actor_user_id,
        mailbox_id=mailbox_id,
        message_ids=ids,
        label_id=label_id,
        mailbox_address=mailbox["email"],
    )
    with connect() as conn:
        changed = conn.execute(
            "UPDATE gmail_mailboxes SET label_id=?,connection_state='active',updated_at=? "
            "WHERE id=? AND connection_state='needs_label'",
            (label_id, now(), mailbox_id),
        )
        if changed.rowcount != 1:
            raise RuntimeError("mailbox activation changed; retry safely")
    return results
