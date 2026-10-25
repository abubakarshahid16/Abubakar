"""The browser's sign-in (owner order 164.2, PR #1242): an HttpOnly cookie, its
CSRF layers, where `Secure` is set, and sign-out that ends the token on the
server. Split from `auth.py` (which keeps tokens, passwords and
`resolve_user_id`); it imports `auth`, and `auth.resolve_user_id` imports it at
call time."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from . import auth
from .config import settings
from .db import connect

_log = logging.getLogger("rag_intelligence.auth")

# ------------------------------------------------------------ the cookie session
#
# Owner order 164.2: the browser's login lives in an HttpOnly cookie, so the
# page never holds the token and a reload keeps the user signed in. The token
# is the SAME signed blob (same 8 hours, same revoke and deactivate checks);
# only where the browser keeps it changes. A bearer header still works and
# wins: it is not cookie-borne, so it needs none of the CSRF layers below.

COOKIE_NAME = "rag_session"
#: Any request that rides on the cookie must carry this header: a page on another
#: site cannot set it without a CORS preflight, and the CORS list is the dev
#: origin only.
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "rag-ui"
#: The Vite dev origins (the same list the CORS middleware allows).
DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


def _origin_ok(request: Request) -> bool:
    """No Origin header (a tool, not a browser page) is fine; a browser page's
    Origin must be this server's own host or the dev origin."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    if origin in DEV_ORIGINS:
        return True
    own = (request.headers.get("host") or "").lower()
    return bool(own) and origin.lower().partition("://")[2] == own


def csrf_ok(request: Request) -> bool:
    """True when a cookie-borne request may act: EVERY method, a read included,
    needs the custom header AND a matching Origin. A GET is not harmless here: it
    can run the model, and a page on another localhost port is the same SITE, so
    SameSite=Strict alone would still send the cookie with an <img> or a link. No
    such tag or form can set the header, so the cookie is useless to any page but
    ours (s2's review of #1242). The bearer path is not cookie-borne and is
    unchanged."""
    return request.headers.get(CSRF_HEADER) == CSRF_VALUE and _origin_ok(request)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def cookie_plan(request: Request) -> bool | None:
    """`Secure` for the sign-in cookie, or None when the cookie is refused.

    `auto` (default) goes by where the request came from, never by a header a
    client can forge: https is Secure; plain http on a loopback host is allowed
    (Safari drops a Secure cookie there); plain http on a network address would
    put the cookie on the wire, so it is refused (None) and the login falls back
    to the bearer token. `X-Forwarded-Proto` is not read: a proxy that
    terminates https tells the server through uvicorn's own proxy-headers
    setting. `false` forces non-Secure (an owner's explicit choice); `true`
    keeps Secure on loopback too."""
    mode = str(settings.auth_cookie_secure or "auto").strip().lower()
    if mode == "false":
        return False
    if request.url.scheme == "https":
        return True
    if (request.url.hostname or "").lower() in LOOPBACK_HOSTS:
        return mode == "true"
    return None


def session_login(session: str, request: Request, response, result: dict) -> dict:
    """The browser's login (`session == "cookie"`): the token goes into the
    HttpOnly cookie and out of the body. Refused (see `cookie_plan`) it stays in
    the body, the bearer way, and the page keeps it in memory."""
    secure = cookie_plan(request) if session == "cookie" else None
    if secure is None:
        return result
    response.set_cookie(
        COOKIE_NAME,
        result["token"],
        max_age=settings.auth_token_seconds,
        path="/",
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    return {**result, "token": None}


router = APIRouter()


class LogoutResult(BaseModel):
    signed_out: bool


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expiry(token: str) -> float:
    return float(json.loads(auth._unb64(token.split(".", 1)[0])).get("x", 0))


def is_signed_out(token: str) -> bool:
    """True when this exact token was ended by a sign-out. No table yet means
    nobody ever signed out; any other database fault refuses (fail closed)."""
    try:
        row = connect().execute(
            "SELECT 1 FROM revoked_sessions WHERE token_hash = ?", (_token_hash(token),)
        )
        return row.fetchone() is not None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return False
        _log.warning(
            "sign-out list could not be read (%s); refused", type(exc).__name__
        )
        return True


def sign_out(token: str, now: float | None = None) -> bool:
    """End THIS token (a copy of it stops working at once). The user's other
    sign-ins, a script's token and the user's `token_epoch` are untouched. Only
    a genuine, unexpired token is recorded; the row is kept until it would have
    expired anyway, and expired rows are dropped here."""
    now = time.time() if now is None else now
    if not auth.read_token(token, now):
        return False
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS revoked_sessions ("
            "token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
        )
        conn.execute("DELETE FROM revoked_sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT OR IGNORE INTO revoked_sessions (token_hash, expires_at) VALUES (?, ?)",
            (_token_hash(token), _expiry(token)),
        )
    return True


def request_token(request: Request) -> str:
    """The token a request signs in with: the bearer header's, else the browser's
    cookie - and a cookie only when it passes the CSRF layers (a write needs the
    custom header and a matching Origin). An invalid bearer never falls back to
    the cookie. "" when there is none."""
    bearer = _presented_token(request, cookie=False)
    if bearer:
        return bearer
    token = request.cookies.get(COOKIE_NAME) or ""
    return token if token and csrf_ok(request) else ""


def _presented_token(request: Request, *, cookie: bool = True) -> str:
    """The bearer token if there is one, else the cookie's value."""
    scheme, _, bearer = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and bearer.strip():
        return bearer.strip()
    return (request.cookies.get(COOKIE_NAME) or "") if cookie else ""


@router.post("/api/auth/logout", response_model=LogoutResult)
def logout(request: Request, response: Response):
    """Sign out: the cookie is cleared AND the token this request presented
    (cookie or bearer) is ended on the server, so a copy of it is refused for
    the rest of its 8 hours. Needs no session (nobody signed in is still fine);
    only the one token is ended, not the user's other sign-ins."""
    token = _presented_token(request)
    if token:
        sign_out(token)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=bool(cookie_plan(request)),
    )
    return {"signed_out": True}
