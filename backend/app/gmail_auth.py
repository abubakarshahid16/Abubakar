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
from .config import settings
from .db import connect
from .gmail_client import GmailApiClient
from .technical_queries import now, require_enabled

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
#: READ ONLY: what connecting a mailbox asks. Sending to a contractor is a later, separate consent (owner, 25 Nov 2026): never asked
#: until the owner writes "sending approved".
SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
#: The TEST send to the owner's OWN mailbox (owner, 26 Nov 2026 23:14 PKT): asked ONLY by the separate re-grant of a mailbox already
#: connected (`start(..., purpose="test_send")`), and only while TECHNICAL_QUERY_TEST_SEND_ENABLED is on (technical_query_test_send).
TEST_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TEST_SEND = "test_send"


#: What Google says when a Workspace company's admin has not allowed this app (the token step's error, or the return address's `error`).
ADMIN_BLOCKS = frozenset({"admin_policy_enforced", "org_internal", "access_blocked", "app_not_allowed"})
ADMIN_WORDS = "Your company's Google admin must allow this app."


class CompanyAdminMustAllow(ValueError):
    """Google refused the connection because the company's Google admin has not allowed this app (said in one plain line, never a raw error)."""


def _config() -> tuple[str, str]:
    client_id = (os.environ.get("GMAIL_CLIENT_ID") or settings.gmail_client_id).strip()
    redirect_uri = (
        os.environ.get("GMAIL_REDIRECT_URI") or settings.gmail_redirect_uri
    ).strip()
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
    if not _client_secret():
        raise RuntimeError("Gmail OAuth client secret is not configured")
    gmail_credentials._keyring()


def _client_secret() -> str:
    return (
        os.environ.get("GMAIL_CLIENT_SECRET") or settings.gmail_client_secret
    ).strip()


def start(user_id: str | None, purpose: str = "read") -> str:
    """The Google consent address. `purpose="test_send"` is the separate re-grant that adds the send scope to an already connected
    mailbox, for TEST sends to that mailbox itself; only while its switch is on."""
    if purpose not in {"read", TEST_SEND}:
        raise ValueError("unknown connection purpose")
    if purpose == TEST_SEND and not settings.technical_query_test_send_enabled:
        raise RuntimeError("test sending is switched off")
    client_id, redirect_uri = _config()
    state = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute(
            "INSERT INTO gmail_oauth_states(state,user_id,created_at,purpose) VALUES (?,?,?,?)",
            (state, user_id, now(), purpose),
        )
    scopes = (*SCOPES, TEST_SEND_SCOPE) if purpose == TEST_SEND else SCOPES
    return (
        AUTH_ENDPOINT
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
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
    require_enabled()  # a real call to Google only while the feature's switch is on
    response = httpx.post(
        TOKEN_ENDPOINT,
        data=data,
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    )
    if response.status_code >= 400:
        try:
            reason = str(response.json().get("error") or "")
        except ValueError:
            reason = ""
        if reason in ADMIN_BLOCKS:
            raise CompanyAdminMustAllow(ADMIN_WORDS)
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
    purpose = _purpose(state)
    user_id = consume_state(state)
    if not user_id or not code:
        raise ValueError("Gmail authorization state is invalid or expired")
    client_id, redirect_uri = _config()
    client_secret = _client_secret()
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
    if purpose == TEST_SEND:
        return _grant_test_send(user_id, address, tokens, refresh_token, store)
    with connect() as conn:  # connecting again a mailbox that was revoked or in error: the same row takes the new token and chooses its label again
        again = conn.execute(
            "SELECT id FROM gmail_mailboxes WHERE lower(email)=? AND owner_user_id=? AND connection_state IN ('revoked','error')", (address, user_id)
        ).fetchone()
    if again is not None:
        store.save_refresh_token(again["id"], refresh_token)
        with connect() as conn:
            conn.execute(
                "UPDATE gmail_mailboxes SET connection_state='needs_label',label_id=NULL,last_history_id=?,status_note=NULL,updated_at=? WHERE id=?",
                (history_id, now(), again["id"]),
            )
        return {"mailbox_id": again["id"], "email": address, "connection_state": "needs_label"}
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
    return {
        "mailbox_id": mailbox_id,
        "email": address,
        "connection_state": "needs_label",
    }


def _purpose(state: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT purpose FROM gmail_oauth_states WHERE state=?", (state,)).fetchone()
    return str((row["purpose"] if row else None) or "read")


def _grant_test_send(user_id: str, address: str, tokens: dict[str, Any], refresh_token: str, store: Any) -> dict[str, str]:
    """The re-grant: the SAME mailbox (this person's, already connected) keeps reading and may now send TEST messages to itself. Google
    must have granted the send scope; the new token replaces the old one (it reads too)."""
    if not settings.technical_query_test_send_enabled:
        raise RuntimeError("test sending is switched off")
    if TEST_SEND_SCOPE not in str(tokens.get("scope") or "").split():
        raise RuntimeError("Google did not grant sending: allow it on Google's page and try again")
    with connect() as conn:
        row = conn.execute(
            "SELECT id, connection_state FROM gmail_mailboxes WHERE lower(email)=? AND owner_user_id=? AND connection_state IN ('active','needs_label')",
            (address, user_id),
        ).fetchone()
    if row is None:
        raise ValueError("connect this mailbox first, then allow test sending")
    store.save_refresh_token(row["id"], refresh_token)
    with connect() as conn:
        conn.execute("UPDATE gmail_mailboxes SET test_send_granted_at=?,updated_at=? WHERE id=?", (now(), now(), row["id"]))
    return {"mailbox_id": row["id"], "email": address, "connection_state": row["connection_state"], "test_send": "granted"}


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
    client_secret = _client_secret()
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
