"""WHO a request is. `access.py` decides WHAT it may see.

The dependency runs one way and must keep running one way: `main.py` calls
`install()` at startup, which hands `resolve_user_id` to
`access.set_user_resolver`. **This module must never import `access`**, and
nothing here may import `search`, `answer` or `chat`.

THE BOUNDARY IS THIS MODULE'S RETURN TYPE. `resolve_user_id` returns
`str | None` and nothing wider. The client controls which row is looked up; it
can never control what the lookup returns, because the scope is derived
server-side from the grant tables afterwards. If this signature ever widens to
a scope, a set of ids, or a role name, the boundary has moved into the request
and the guarantee is gone.

THE TOKEN is a signed opaque bearer - HMAC-SHA256 over a small JSON blob - not
a JWT. `requirements.txt` carries no JWT library and the target is air-gapped
after setup. A JWT parser would buy algorithm negotiation, a `kid` header and
the `alg: none` family, against a threat model of a handful of known users on
loopback. HMAC over JSON has exactly one algorithm because there is no field in
which to name another. This is the simpler option, chosen deliberately.

NOT A SESSION TABLE. More conventional, and it would give instant revocation.
Rejected: it puts a row insert on every login and a SELECT on every request
against the one SQLite file ingestion is already writing to, and an
uncollected expired-session table is an operational wart on a machine nobody
administers.

REVOCATION, three cases, cheapest first:

  deleted       ON DELETE CASCADE removes user_roles, so the scope resolves to
                frozenset(). Already true, no code here.
  deactivated   `is_active` is re-read on EVERY request, so a deactivation
                takes effect on the next call rather than at token expiry.
  forced logout increments `users.token_epoch`; every token carries the epoch
  it was issued against and is rejected after that increment.

Revocation is therefore next-request, not instant. Said plainly rather than
implied.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from typing import TYPE_CHECKING

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .config import settings
from .db import connect

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import Request

#: Argon2id at the library's defaults, which track the current OWASP guidance.
#: Not tuned here: a hand-picked memory cost on one laptop is a number nobody
#: can defend, and the library's default moves with the library.
_hasher = PasswordHasher()

#: A real Argon2id hash of a value no one can log in with, verified on every
#: failed lookup so that "no such user" and "wrong password" take the same
#: work. Without it, a missing user returns in microseconds and a wrong
#: password in ~50 ms, and the difference enumerates the user list.
#:
#: Four lines, and not optional.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))

TOKEN_VERSION = 1


class AuthError(Exception):
    """Login refused. Carries a code the API maps to a status."""

    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


# --------------------------------------------------------------- the secret


def _secret() -> bytes:
    """The signing key.

    Under `demo_required` a weak or absent secret is refused at STARTUP rather
    than at first login, because a system that boots and then rejects everyone
    looks like a broken deployment, and one that boots with a guessable key
    looks like a working one.
    """
    raw = (settings.auth_secret or "").strip()
    return raw.encode("utf-8")


def check_secret_or_refuse() -> None:
    """Called from startup. Only enforces when authentication is required."""
    from .access import AUTH_DISABLED

    if settings.auth_mode == AUTH_DISABLED:
        return
    raw = (settings.auth_secret or "").strip()
    if len(raw) < 32:
        raise RuntimeError(
            "AUTH_SECRET must be at least 32 characters when AUTH_MODE is "
            "demo_required. Generate one with: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\" and put it in backend/.env. "
            "See .env.example."
        )


# ---------------------------------------------------------------- the token


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user_id: str, now: float | None = None) -> str:
    """`payload.signature`, both base64url.

    Lifetime is 8 hours and there is no refresh token. A refresh flow exists to
    make short tokens tolerable; a long token is the alternative to it, not a
    companion. Eight hours is justified against THIS system: a Tier 2 answer
    takes ~50 s and an ingest runs for many minutes, so a 15-minute token means
    a login screen appearing mid-demo.
    """
    now = time.time() if now is None else now
    row = connect().execute("SELECT token_epoch FROM users WHERE id = ?", (user_id,)).fetchone()
    epoch = int(row["token_epoch"]) if row else 0
    body = json.dumps(
        {"u": user_id, "e": epoch, "v": TOKEN_VERSION,
         "x": int(now + settings.auth_token_seconds)},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(_secret(), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(signature)}"


def read_token(token: str, now: float | None = None) -> str | None:
    """The user id a token claims, or None. NEVER raises.

    A malformed token is not an error to be reported in detail: every failure
    here returns None and lands on `empty_scope()`. Telling the caller which
    part of its forgery was wrong is free help.
    """
    now = time.time() if now is None else now
    try:
        body_b64, signature_b64 = token.split(".", 1)
        body = _unb64(body_b64)
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()
        # Constant time: a byte-by-byte compare leaks the correct prefix
        # length, which is enough to forge a signature one byte at a time.
        if not hmac.compare_digest(expected, _unb64(signature_b64)):
            return None
        claims = json.loads(body)
        if claims.get("v") != TOKEN_VERSION:
            return None
        if float(claims.get("x", 0)) <= now:
            return None
        user_id = claims.get("u")
        return user_id if isinstance(user_id, str) and user_id else None
    except Exception:  # noqa: BLE001 - any malformed token is simply not a token
        return None


# ------------------------------------------------------------ the rate limit


class _Limiter:
    """Failed logins per email, in memory, with a lock.

    NOT a table. A row per failed login turns an unauthenticated endpoint into
    an unauthenticated WRITER against the SQLite file ingestion is writing to,
    which is a denial-of-service primitive handed to anyone who can reach the
    port. The durable record is `audit_events`, written on the way past.

    It does not survive a restart, and one process holds it. Said plainly
    because an operator who believes otherwise will not notice it reset.
    """

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    #: The countdown is reported to the nearest 30 seconds, rounded UP.
    #:
    #: An exact remaining time says when the FIRST failure in the window
    #: happened, which is a fact about somebody else's attempts against that
    #: address - a quieter version of the enumeration oracle the constant-time
    #: verify closes. It also made two refusals differ by one second, so
    #: "the two 429s are identical" could not be asserted at all.
    #:
    #: Coarse is also better for the reader: nobody acts differently on 298
    #: seconds than on 300.
    GRANULARITY = 30

    def check(self, key: str, now: float) -> int | None:
        """Seconds to wait, rounded up, or None to proceed."""
        window = settings.auth_lockout_seconds
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < window]
            self._fails[key] = recent
            if len(recent) >= settings.auth_max_attempts:
                remaining = window - (now - recent[0])
                buckets = max(1, math.ceil(remaining / self.GRANULARITY))
                return buckets * self.GRANULARITY
        return None

    def record_failure(self, key: str, now: float) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


_limiter = _Limiter()


def reset_limiter() -> None:
    """For tests. Production has no reason to call this."""
    global _limiter
    _limiter = _Limiter()


# ----------------------------------------------------------------- the audit


def _audit(action: str, outcome: str, username: str, user_id: str | None = None,
           detail: str | None = None) -> None:
    """Durable record of an authentication attempt.

    `actor_username` is denormalised on purpose (see db.py): a deleted user
    must not erase the record of what they did.
    """
    from datetime import datetime, timezone

    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO audit_events
                       (id, at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, ?, 'session', NULL, ?, ?)""",
                (secrets.token_hex(12),
                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 user_id, username[:200], action, outcome, detail),
            )
    except Exception:  # noqa: BLE001 - an unwritable audit must not block login
        pass


# ------------------------------------------------------------------ the login


def login(email: str, password: str, now: float | None = None) -> dict:
    """Verify credentials and issue a token. Raises AuthError on refusal.

    ONE failure message for every credential failure. "No such user" and
    "wrong password" are the same sentence and the same amount of work - see
    _DUMMY_HASH - because the pair of them is a user enumeration oracle.
    """
    now = time.time() if now is None else now
    key = (email or "").strip().lower()

    wait = _limiter.check(key, now)
    if wait is not None:
        _audit("login_failed", "rate_limited", key)
        raise AuthError(
            "rate_limited",
            f"Too many failed attempts. Try again in {wait} seconds.",
            retry_after=wait,
        )

    row = connect().execute(
        "SELECT id, email, display_name, password_hash, is_active "
        "FROM users WHERE lower(email) = ?",
        (key,),
    ).fetchone()

    stored = row["password_hash"] if row else _DUMMY_HASH
    try:
        _hasher.verify(stored, password or "")
        ok = True
    except (VerifyMismatchError, VerificationError):
        ok = False
    except Exception:  # noqa: BLE001 - a corrupt hash is a failed login
        ok = False

    # An inactive user is refused with the SAME message. Saying "your account
    # is disabled" confirms the address exists.
    if not ok or row is None or not row["is_active"]:
        _limiter.record_failure(key, now)
        _audit("login_failed", "denied", key,
               user_id=row["id"] if row else None)
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    _limiter.clear(key)
    from datetime import datetime, timezone

    conn = connect()
    with conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["id"]),
        )
    _audit("login", "allowed", row["email"], user_id=row["id"])
    return {
        "token": issue_token(row["id"], now=now),
        "user": describe(row["id"]) or {},
        "expires_in_seconds": settings.auth_token_seconds,
    }


def describe(user_id: str) -> dict | None:
    """The identity a client may know about itself. Roles, never grants.

    Document ids are deliberately absent: the scope is server-side, and a
    client that is told which documents it may see has been handed a list to
    check its guesses against.
    """
    conn = connect()
    row = conn.execute(
        "SELECT id, email, display_name, is_active FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    roles = [
        r["name"] for r in conn.execute(
            """SELECT r.name FROM roles r
               JOIN user_roles ur ON ur.role_id = r.id
               WHERE ur.user_id = ? ORDER BY r.name""",
            (user_id,),
        ).fetchall()
    ]
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "roles": roles,
    }


# -------------------------------------------------------------- the resolver


def resolve_user_id(request: Request) -> str | None:
    """The entire client-influenced surface of authorisation.

    Returns `str | None` and nothing wider. See the module docstring: this
    signature IS the boundary.

    `is_active` is re-read here rather than trusted from the token, so
    deactivating a user takes effect on their next request instead of when
    their token expires.
    """
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    user_id = read_token(token.strip())
    if not user_id:
        return None
    row = connect().execute(
        "SELECT id FROM users WHERE id = ? AND is_active = 1 AND token_epoch = ?",
        (user_id, _token_epoch(token.strip())),
    ).fetchone()
    return row["id"] if row else None


def _token_epoch(token: str) -> int:
    try:
        body_b64, _ = token.split(".", 1)
        claims = json.loads(_unb64(body_b64))
        return int(claims.get("e", 0))
    except Exception:
        return -1


def revoke_user_tokens(user_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE users SET token_epoch = token_epoch + 1 WHERE id = ?", (user_id,)
        )
        return cur.rowcount > 0


def install() -> None:
    """The only wiring. Called once from `lifespan`."""
    from . import access

    check_secret_or_refuse()
    access.set_user_resolver(resolve_user_id)
