"""Gmail OAuth preparation; no account is contacted until the callback is used."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from . import gmail_credentials
from .db import connect
from .gmail_client import GmailApiClient
from .technical_queries import now

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)


def _config() -> tuple[str, str]:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    redirect_uri = os.environ.get("GMAIL_REDIRECT_URI", "").strip()
    parsed = urlparse(redirect_uri)
    loopback = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    secure = parsed.scheme == "https" and bool(parsed.hostname)
    if not client_id or not redirect_uri or not (secure or loopback):
        raise RuntimeError(
            "Gmail OAuth requires HTTPS or a local loopback redirect URI"
        )
    return client_id, redirect_uri


def connection_ready() -> None:
    _config()
    if not os.environ.get("GMAIL_CLIENT_SECRET", "").strip():
        raise RuntimeError("Gmail OAuth client secret is not configured")
    gmail_credentials._keyring()


def start(user_id: str | None) -> str:
    client_id, redirect_uri = _config()
    state = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute(
            "INSERT INTO gmail_oauth_states(state,user_id,created_at) VALUES (?,?,?)",
            (state, user_id, now()),
        )
    return (
        AUTH_ENDPOINT
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
    )


def consume_state(state: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id,used_at,created_at FROM gmail_oauth_states WHERE state=?",
            (state,),
        ).fetchone()
        if row is None or row["used_at"] is not None:
            return None
        created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if created < datetime.now(UTC) - timedelta(minutes=10):
            return None
        changed = conn.execute(
            "UPDATE gmail_oauth_states SET used_at=? WHERE state=? AND used_at IS NULL",
            (now(), state),
        )
        if changed.rowcount != 1:
            return None
        return row["user_id"]


def validate_state(state: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id,used_at FROM gmail_oauth_states WHERE state=?", (state,)
        ).fetchone()
        return None if row is None or row["used_at"] is not None else row["user_id"]


def _exchange(data: dict[str, str]) -> dict[str, Any]:
    response = httpx.post(TOKEN_ENDPOINT, data=data, timeout=20)
    response.raise_for_status()
    return response.json()


def complete(
    code: str,
    state: str,
    *,
    exchange: Callable[[dict[str, str]], dict[str, Any]] = _exchange,
    profile: Callable[[str], dict[str, Any]] | None = None,
    store: Any = gmail_credentials,
) -> dict[str, str]:
    """Exchange one consent code and store the refresh token in Keychain."""
    user_id = consume_state(state)
    if not user_id or not code:
        raise ValueError("Gmail authorization state is invalid or expired")
    client_id, redirect_uri = _config()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    if not client_secret:
        raise RuntimeError("Gmail OAuth client secret is not configured")
    tokens = exchange(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    refresh_token = tokens.get("refresh_token")
    access_token_value = tokens.get("access_token")
    if not refresh_token or not access_token_value:
        raise RuntimeError("Gmail did not grant offline access")
    mailbox_profile = (
        profile(access_token_value)
        if profile
        else GmailApiClient(access_token_value).profile()
    )
    address = str(mailbox_profile.get("emailAddress") or "").strip().lower()
    history_id = str(mailbox_profile.get("historyId") or "").strip()
    if not address or "@" not in address or not history_id:
        raise RuntimeError("Gmail mailbox identity could not be verified")
    mailbox_id = str(uuid.uuid4())
    store.save_refresh_token(mailbox_id, refresh_token)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,connection_state,connected_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (mailbox_id, user_id, address, history_id, "needs_label", now(), now()),
            )
    except Exception:
        store.delete_refresh_token(mailbox_id)
        raise
    return {"mailbox_id": mailbox_id, "email": address, "connection_state": "needs_label"}


def access_token(
    mailbox_id: str,
    *,
    exchange: Callable[[dict[str, str]], dict[str, Any]] = _exchange,
) -> str:
    with connect() as conn:
        mailbox = conn.execute(
            "SELECT connection_state FROM gmail_mailboxes WHERE id=?", (mailbox_id,)
        ).fetchone()
    if mailbox is None or mailbox["connection_state"] not in {"active", "needs_label"}:
        raise PermissionError("Gmail mailbox is not active")
    client_id, _ = _config()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    if not client_secret:
        raise RuntimeError("Gmail OAuth client secret is not configured")
    refreshed = exchange(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": gmail_credentials.get_refresh_token(mailbox_id),
            "grant_type": "refresh_token",
        }
    )
    token = refreshed.get("access_token")
    if not token:
        raise RuntimeError("Gmail access could not be refreshed")
    return str(token)
