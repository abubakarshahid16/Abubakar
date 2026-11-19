"""Minimal Gmail API client used by the query worker.

The client is injectable and does not log tokens or message bodies. Tests use a
fake transport; no real Gmail request is made by the test suite.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass(frozen=True)
class GmailMessage:
    provider_message_id: str
    thread_id: str | None
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str
    body: str
    received_at: str | None
    attachments: list[dict[str, Any]]


class GmailApiClient:
    def __init__(self, access_token: str, transport: Callable[..., Any] | None = None):
        if not access_token:
            raise ValueError("an access token is required")
        self._token = access_token
        self._transport = transport

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._transport:
            response = self._transport(method, BASE + path, headers=headers, **kwargs)
        else:
            response = httpx.request(
                method, BASE + path, headers=headers, timeout=30, **kwargs
            )
        response.raise_for_status()
        return response.json()

    def history(self, start_history_id: str) -> list[str]:
        payload = self._request(
            "GET",
            "/history",
            params={"startHistoryId": start_history_id, "historyTypes": "messageAdded"},
        )
        ids: list[str] = []
        for item in payload.get("history", []):
            for added in item.get("messagesAdded", []):
                message = added.get("message") or {}
                if message.get("id"):
                    ids.append(str(message["id"]))
        return list(dict.fromkeys(ids))

    def message(self, message_id: str) -> GmailMessage:
        payload = self._request(
            "GET", f"/messages/{message_id}", params={"format": "full"}
        )
        return normalize_message(payload)

    def watch(self, topic_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/watch",
            json={
                "topicName": topic_name,
                "labelIds": ["INBOX"],
                "labelFilterBehavior": "INCLUDE",
            },
        )


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in payload.get("headers", [])
    }


def _decode(data: str | None) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
        "utf-8", errors="replace"
    )


def _body(part: dict[str, Any]) -> str:
    mime = part.get("mimeType", "")
    if mime == "text/plain":
        return _decode((part.get("body") or {}).get("data"))
    return "".join(_body(child) for child in part.get("parts", []))


def normalize_message(payload: dict[str, Any]) -> GmailMessage:
    headers = _headers(payload.get("payload") or {})
    attachments: list[dict[str, Any]] = []
    stack = list((payload.get("payload") or {}).get("parts", []))
    while stack:
        part = stack.pop()
        body = part.get("body") or {}
        if part.get("filename"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "media_type": part.get("mimeType", "application/octet-stream"),
                    "size_bytes": int(body.get("size", 0)),
                    "attachment_id": body.get("attachmentId"),
                }
            )
        stack.extend(part.get("parts", []))
    return GmailMessage(
        provider_message_id=str(payload["id"]),
        thread_id=payload.get("threadId"),
        from_address=headers.get("from", ""),
        to_addresses=[x.strip() for x in headers.get("to", "").split(",") if x.strip()],
        cc_addresses=[x.strip() for x in headers.get("cc", "").split(",") if x.strip()],
        subject=headers.get("subject", "(no subject)"),
        body=_body(payload.get("payload") or {}),
        received_at=headers.get("date"),
        attachments=attachments,
    )
