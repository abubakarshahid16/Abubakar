"""Gmail OAuth preparation; no account is contacted until the callback is used."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode, urlparse

from .db import connect
from .technical_queries import now

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
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
            "SELECT user_id,used_at FROM gmail_oauth_states WHERE state=?", (state,)
        ).fetchone()
        if row is None or row["used_at"] is not None:
            return None
        conn.execute(
            "UPDATE gmail_oauth_states SET used_at=? WHERE state=?", (now(), state)
        )
        return row["user_id"]


def validate_state(state: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id,used_at FROM gmail_oauth_states WHERE state=?", (state,)
        ).fetchone()
        return None if row is None or row["used_at"] is not None else row["user_id"]
