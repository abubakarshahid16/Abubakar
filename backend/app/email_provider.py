"""Provider-neutral email notification boundary.

No credentials or network calls live here. Adapters only normalize untrusted
provider notifications; a separate approved worker fetches message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MessageNotification:
    provider: str
    mailbox_id: str | None
    provider_message_id: str
    provider_thread_id: str | None


def graph_notifications(payload: dict[str, Any]) -> list[MessageNotification]:
    values = payload.get("value")
    if not isinstance(values, list):
        raise ValueError("provider notification must contain a value list")
    result: list[MessageNotification] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        resource = str(item.get("resource", ""))
        message_id = (
            item.get("resourceData", {}).get("id")
            if isinstance(item.get("resourceData"), dict)
            else None
        )
        if not message_id:
            message_id = resource.rsplit("/", 1)[-1] if resource else None
        if not message_id:
            continue
        result.append(
            MessageNotification(
                "microsoft_graph", item.get("subscriptionId"), str(message_id), None
            )
        )
    return result


def gmail_notification(payload: dict[str, Any]) -> tuple[str, str] | None:
    data = (
        payload.get("message", {}).get("data")
        if isinstance(payload.get("message"), dict)
        else None
    )
    if not data:
        return None
    return "gmail", str(data)
