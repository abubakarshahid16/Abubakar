"""Retry-safe Gmail notification worker boundary."""

from __future__ import annotations

import json
from email.message import EmailMessage
from typing import Any

from .db import connect
from .gmail_client import GmailApiClient
from .technical_queries import import_message, now


def process_history(
    client: GmailApiClient,
    history_id: str,
    actor_user_id: str | None,
    *,
    mailbox_id: str,
) -> list[dict[str, Any]]:
    results = []
    for message_id in client.history(history_id):
        message = client.message(message_id)
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
                "attachments": message.attachments,
            },
            actor_user_id,
            False,
            True,
        )
        results.append({"query_id": item.get("id"), "duplicate": duplicate})
    return results


def send_approved(
    client: GmailApiClient,
    query_id: str,
    draft_id: str,
    to_addresses: list[str],
    cc_addresses: list[str],
    subject: str,
    body: str,
    idempotency_key: str,
) -> str:
    """Send one approved message; the database key prevents a second send."""
    with connect() as conn:
        prior = conn.execute(
            "SELECT provider_message_id,state FROM query_sends WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if prior and prior["provider_message_id"]:
            return str(prior["provider_message_id"])
        if prior is not None:
            raise RuntimeError(
                "an earlier send attempt has no provider id; reconcile before retrying"
            )
        if prior is None:
            conn.execute(
                "INSERT INTO query_sends(id,query_id,draft_id,idempotency_key,to_addresses,cc_addresses,state,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    idempotency_key,
                    query_id,
                    draft_id,
                    idempotency_key,
                    json.dumps(to_addresses),
                    json.dumps(cc_addresses),
                    "sending",
                    now(),
                ),
            )
    message = EmailMessage()
    message["To"] = ", ".join(to_addresses)
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    message["Subject"] = subject
    message.set_content(body)
    try:
        provider_id = client.send(message.as_string())
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE query_sends SET state='failed',error=? WHERE idempotency_key=?",
                (str(exc)[:500], idempotency_key),
            )
        raise
    with connect() as conn:
        conn.execute(
            "UPDATE query_sends SET state='sent',provider_message_id=? WHERE idempotency_key=?",
            (provider_id, idempotency_key),
        )
        conn.execute(
            "UPDATE technical_queries SET status='sent',updated_at=? WHERE id=?",
            (now(), query_id),
        )
    return provider_id
