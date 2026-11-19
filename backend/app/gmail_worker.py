"""Retry-safe Gmail notification worker boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from email.message import EmailMessage
from email.utils import parseaddr
from io import BytesIO
from typing import Any

import httpx

from . import access
from . import upload as upload_mod
from .access import AccessScope
from .config import settings
from .db import connect
from .gmail_client import GmailApiClient
from .technical_queries import get, import_message, link_attachment, now
from .technical_query_docx import render


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
        message = client.message(message_id)
        if label_id and label_id not in message.label_ids:
            continue
        if (
            mailbox_address
            and parseaddr(message.from_address)[1].casefold()
            == mailbox_address.casefold()
        ):
            continue
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
            row, _, duplicate_of = upload_mod.ingest(
                BytesIO(content), source["filename"]
            )
            if duplicate_of is not None and settings.auth_mode != access.AUTH_DISABLED:
                if not access.scope_for_user(actor_user_id).may_read(row["id"]):
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
        results.append({"query_id": item.get("id"), "duplicate": duplicate})
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


def send_approved(
    client: GmailApiClient,
    query_id: str,
    draft_id: str,
    scope: AccessScope,
    idempotency_key: str,
    mailbox_address: str,
) -> str:
    """Send one approved response; an uncertain provider result needs manual reconciliation.

    The API invokes this only after an explicit authorised send action.
    Tests pass an in-memory fake client and never contact Gmail.
    """
    if not scope.is_admin or not scope.user_id:
        raise PermissionError("an authorised sender is required")
    if len(idempotency_key) < 8:
        raise ValueError("an idempotency key is required")
    with connect() as conn:
        prior = conn.execute(
            "SELECT query_id,state,provider_message_id FROM query_sends WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if prior:
            if prior["query_id"] != query_id:
                raise ValueError("the send key belongs to a different query")
            if prior["state"] == "sent" and prior["provider_message_id"]:
                return prior["provider_message_id"]
            raise RuntimeError(
                "send outcome is uncertain; reconcile the mailbox before retrying"
            )

    item = get(query_id, scope.user_id, scope.is_admin, scope.unrestricted)
    if item is None:
        raise ValueError("technical query not found")
    if item["status"] != "approved":
        raise ValueError("only an approved query can be sent")
    draft = item["drafts"][-1] if item["drafts"] else None
    if (
        draft is None
        or draft["id"] != draft_id
        or not any(
            decision["decision"] == "approve" and decision["draft_id"] == draft_id
            for decision in item["decisions"]
        )
    ):
        raise ValueError("the latest draft has not been approved")
    if not item["messages"]:
        raise ValueError("the original email is missing")
    first = item["messages"][0]
    recipient = parseaddr(first["from_address"])[1]
    sender = parseaddr(mailbox_address)[1]
    if not recipient or "@" not in recipient or not sender or "@" not in sender:
        raise ValueError("the sender or original recipient is invalid")
    if "\n" in first["from_address"] or "\r" in first["from_address"]:
        raise ValueError("the original sender is invalid")
    if sender.casefold() not in {
        parseaddr(address)[1].casefold()
        for address in first["to_addresses"] + first["cc_addresses"]
    }:
        raise ValueError("the connected mailbox was not an original recipient")
    if not scope.unrestricted and any(
        evidence["document_id"] not in scope.allowed_document_ids
        for evidence in item["evidence"]
    ):
        raise PermissionError("source document access changed after approval")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = (
        first["subject"]
        if first["subject"].lower().startswith("re:")
        else f"Re: {first['subject']}"
    )
    if (
        first.get("internet_message_id")
        and "\n" not in first["internet_message_id"]
        and "\r" not in first["internet_message_id"]
    ):
        message["In-Reply-To"] = first["internet_message_id"]
        message["References"] = first["internet_message_id"]
    domain = sender.rsplit("@", 1)[-1]
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:20]
    message["Message-ID"] = f"<tq-{query_id}-{digest}@{domain}>"
    message.set_content(draft["answer"])
    document = render(item)
    message.add_attachment(
        document.read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"technical-query-{query_id}.docx",
    )

    send_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO query_sends(id,query_id,draft_id,idempotency_key,to_addresses,cc_addresses,state,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                send_id,
                query_id,
                draft_id,
                idempotency_key,
                json.dumps([recipient]),
                "[]",
                "sending",
                now(),
            ),
        )
        conn.execute(
            "UPDATE technical_queries SET status='send_pending',updated_at=? WHERE id=?",
            (now(), query_id),
        )
        conn.execute(
            "INSERT INTO query_events(query_id,actor_user_id,event,detail,created_at) VALUES (?,?,?,?,?)",
            (query_id, scope.user_id, "send_requested", f"draft={draft_id}", now()),
        )
    try:
        provider_id = client.send(
            message.as_string(), thread_id=first.get("provider_thread_id")
        )
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE query_sends SET state='uncertain',error='provider outcome requires reconciliation' WHERE id=?",
                (send_id,),
            )
        raise RuntimeError(
            "send outcome is uncertain; reconcile the mailbox before retrying"
        ) from exc
    with connect() as conn:
        conn.execute(
            "UPDATE query_sends SET state='sent',provider_message_id=? WHERE id=?",
            (provider_id, send_id),
        )
        conn.execute(
            "UPDATE technical_queries SET status='sent',updated_at=? WHERE id=?",
            (now(), query_id),
        )
        conn.execute(
            "INSERT INTO query_events(query_id,actor_user_id,event,detail,created_at) VALUES (?,?,?,?,?)",
            (
                query_id,
                scope.user_id,
                "sent",
                f"provider_message_id={provider_id}",
                now(),
            ),
        )
    return provider_id
