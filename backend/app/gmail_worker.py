"""Retry-safe Gmail notification worker boundary."""

from __future__ import annotations

from typing import Any

from .gmail_client import GmailApiClient
from .technical_queries import import_message


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
