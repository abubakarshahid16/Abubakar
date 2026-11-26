"""Minimal Gmail API client used by the query worker.

The client is injectable and does not log tokens or message bodies. Tests use a
fake transport; no real Gmail request is made by the test suite.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

import httpx

from .technical_queries import require_enabled

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
    label_ids: tuple[str, ...] = ()


class GmailApiClient:
    def __init__(self, access_token: str, transport: Callable[..., Any] | None = None):
        if not access_token:
            raise ValueError("an access token is required")
        self._token = access_token
        self._transport = transport

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._transport is None:
            require_enabled()  # a real Gmail call only while the feature's switch is on
        if self._transport:
            response = self._transport(method, BASE + path, headers=headers, **kwargs)
        else:
            response = httpx.request(
                method,
                BASE + path,
                headers=headers,
                timeout=30,
                follow_redirects=False,
                trust_env=False,
                **kwargs,
            )
        response.raise_for_status()
        return response.json()

    def send_to_self(self, raw: bytes, own_address: str) -> dict[str, Any]:
        """Send ONE message whose only recipient is `own_address`, the connected mailbox itself (the owner's TEST send, 26 Nov 2026 23:14
        PKT; technical_query_test_send). Refused here too, before any request: another To, any Cc or Bcc, or a resent header. The
        second lock, in the one module that may open a socket to Gmail."""
        from email import message_from_bytes, policy
        from email.utils import getaddresses

        message = message_from_bytes(raw, policy=policy.default)
        to = [a.strip().lower() for _n, a in getaddresses(message.get_all("To", []))]
        others = [h for h in message if h.lower() in {"cc", "bcc", "resent-to", "resent-cc", "resent-bcc"}]
        if to != [own_address.strip().lower()] or others:
            raise PermissionError("a test send goes only to the connected mailbox itself: no other recipient, no Cc, no Bcc")
        return self._request("POST", "/messages/send", json={"raw": base64.urlsafe_b64encode(raw).decode()})

    def history(self, start_history_id: str, label_id: str | None = None) -> list[str]:
        return self.history_delta(start_history_id, label_id)[0]

    def history_delta(
        self, start_history_id: str, label_id: str | None = None
    ) -> tuple[list[str], str]:
        ids: list[str] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        current_history_id = start_history_id
        while True:
            params = {
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded", "labelAdded"],
            }
            if label_id:
                params["labelId"] = label_id
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("GET", "/history", params=params)
            if payload.get("historyId"):
                current_history_id = str(payload["historyId"])
            for item in payload.get("history", []):
                for category in ("messagesAdded", "labelsAdded"):
                    for added in item.get(category, []):
                        message = added.get("message") or {}
                        if message.get("id"):
                            ids.append(str(message["id"]))
            next_token = payload.get("nextPageToken")
            if not next_token:
                break
            if next_token in seen_tokens:
                raise RuntimeError("Gmail history pagination did not advance")
            page_token = str(next_token)
            seen_tokens.add(page_token)
        return list(dict.fromkeys(ids)), current_history_id

    def message(self, message_id: str) -> GmailMessage:
        payload = self._request(
            "GET", f"/messages/{message_id}", params={"format": "full"}
        )
        return normalize_message(payload)

    def profile(self) -> dict[str, Any]:
        return self._request("GET", "/profile")

    def labels(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/labels")
        return [
            label for label in payload.get("labels", []) if label.get("type") == "user"
        ]

    def list_message_ids(self, label_id: str, *, limit: int = 5000) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, Any] = {"labelIds": [label_id], "maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("GET", "/messages", params=params)
            ids.extend(
                str(item["id"])
                for item in payload.get("messages", [])
                if item.get("id")
            )
            if len(ids) > limit:
                raise RuntimeError(
                    "too many labelled messages for initial import; narrow the Gmail label"
                )
            next_token = payload.get("nextPageToken")
            if not next_token:
                return list(dict.fromkeys(ids))
            if next_token in seen_tokens:
                raise RuntimeError("Gmail message pagination did not advance")
            page_token = str(next_token)
            seen_tokens.add(page_token)

    def raw_message(self, message_id: str) -> bytes:
        payload = self._request(
            "GET", f"/messages/{message_id}", params={"format": "raw"}
        )
        encoded = payload.get("raw") or ""
        if not encoded:
            raise ValueError("Gmail did not return the original message")
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        payload = self._request(
            "GET", f"/messages/{message_id}/attachments/{attachment_id}"
        )
        return base64.urlsafe_b64decode(
            (payload.get("data") or "") + "=" * (-len(payload.get("data") or "") % 4)
        )

    def watch(self, topic_name: str, label_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/watch",
            json={
                "topicName": topic_name,
                "labelIds": [label_id],
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


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "li", "tr"}:
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.fragments.append(data)


def _html_body(part: dict[str, Any]) -> str:
    if part.get("mimeType") == "text/html":
        parser = _VisibleHTML()
        parser.feed(_decode((part.get("body") or {}).get("data")))
        return " ".join(" ".join(parser.fragments).split())
    return " ".join(
        value for child in part.get("parts", []) if (value := _html_body(child))
    )


def inline_picture(part: dict[str, Any]) -> bool:
    """A picture shown INSIDE the mail body (a signature logo, a banner): it has a Content-ID the body refers to as "cid:" and is not
    sent as an attachment. Counted apart on the query ("N signature pictures, not attachments"), never uploaded or read."""
    headers = _headers(part)
    disposition = headers.get("content-disposition", "").strip().lower()
    return (
        str(part.get("mimeType", "")).lower().startswith("image/")
        and bool(headers.get("content-id"))
        and not disposition.startswith("attachment")
    )


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
                    "inline_data": body.get("data"),
                    "inline_picture": inline_picture(part),
                }
            )
        stack.extend(part.get("parts", []))
    received_at = None
    if payload.get("internalDate"):
        received_at = (
            datetime.fromtimestamp(int(payload["internalDate"]) / 1000, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    elif headers.get("date"):
        try:
            received_at = (
                parsedate_to_datetime(headers["date"])
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (TypeError, ValueError, OverflowError):
            received_at = None
    return GmailMessage(
        provider_message_id=str(payload["id"]),
        thread_id=payload.get("threadId"),
        from_address=headers.get("from", ""),
        to_addresses=[x.strip() for x in headers.get("to", "").split(",") if x.strip()],
        cc_addresses=[x.strip() for x in headers.get("cc", "").split(",") if x.strip()],
        subject=headers.get("subject", "(no subject)"),
        body=_body(payload.get("payload") or {})
        or _html_body(payload.get("payload") or {}),
        received_at=received_at,
        attachments=attachments,
        label_ids=tuple(payload.get("labelIds") or []),
    )
