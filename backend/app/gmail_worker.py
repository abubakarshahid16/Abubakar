"""Retry-safe Gmail notification worker boundary."""

from __future__ import annotations

from typing import Any

from .gmail_client import GmailApiClient
from .technical_queries import import_message


def process_history(
    client: GmailApiClient,
    history_id: str,
    actor_user_id: str,
    *,
    mailbox_id: str,
) -> list[dict[str, Any]]:
    if not actor_user_id or not mailbox_id:
        raise ValueError("a mailbox owner and mailbox identity are required")
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
            False,
        )
        results.append({"query_id": item.get("id"), "duplicate": duplicate})
    return results


def send_approved(
    _client: GmailApiClient,
    _query_id: str,
    _draft_id: str,
    _to_addresses: list[str],
    _cc_addresses: list[str],
    _subject: str,
    _body: str,
    _idempotency_key: str,
) -> str:
    """Refuse direct sending until approved content and recipient binding exist.

    The former version trusted caller-supplied body, recipients and draft id;
    its name implied checks which it did not perform. It could disclose data
    or send unapproved content if invoked by a future route or worker.
    """
    raise RuntimeError(
        "Gmail sending is disabled until approved draft and recipient verification are implemented"
    )
