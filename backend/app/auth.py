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
  forced logout NOT BUILT. It needs `users.token_epoch`, and the design names
                it as the first thing to drop. Deletion and deactivation cover
                the cases that matter.

Revocation is therefore next-request, not instant. Said plainly rather than
implied.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
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
MIN_PASSWORD_CHARS = 12
FORBIDDEN_PASSWORDS = frozenset({
    "password", "passw0rd", "demo", "demo1234", "changeme", "letmein",
    "welcome", "12345678", "qwerty", "admin", "ragintel",
    "ragintelligence", "rag", "ragintelligencesystem", "nabaa", "aramco",
})

#: Below this, a key is not a key. HMAC-SHA256 accepts any length including
#: zero, so nothing in the crypto complains - `hmac.new(b"", ...)` signs
#: perfectly happily, and an attacker who knows the key is empty can compute
#: the same signature over any payload they like. Under the SHIPPED DEFAULT
#: (`auth_mode=disabled`, `auth_secret=""`) that was the state, so a forged
#: Bearer token naming any user id verified, and that id became `actor` in
#: every admin audit row it touched. 32 bytes is the digest size.
MIN_SECRET_BYTES = 32


class WeakSigningKey(RuntimeError):
    """Refusal to sign with a key that cannot carry a signature.

    Raised, never returned: `issue_token` returning None would be silently
    dropped into a header by a caller that expected a string. `read_token`
    does not raise, because its contract is that it never does - it returns
    None, which lands the request on `empty_scope()`.
    """


class AuthError(Exception):
    """Login refused. Carries a code the API maps to a status."""

    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


def password_problems(password: str, email: str) -> list[str]:
    """Return all reasons a proposed password is unsafe."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_CHARS:
        problems.append(f"must be at least {MIN_PASSWORD_CHARS} characters")
    low = password.lower()
    if low in FORBIDDEN_PASSWORDS:
        problems.append("is too easy to guess")
    elif any(word in low for word in FORBIDDEN_PASSWORDS if word != "admin"):
        problems.append("contains an easily guessed word")
    local = (email.split("@", 1)[0] if email else "").split("+", 1)[0].lower()
    if len(local) >= 3 and local in low:
        problems.append("must not contain the email address")
    if password.strip() != password:
        problems.append("must not start or end with whitespace")
    return problems


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
    # A token signed with a zero-length key is a forgery anybody can repeat.
    # Refused here as well as at startup, because `check_secret_or_refuse`
    # returns early under `AUTH_MODE=disabled` and `settings` can be
    # reassigned afterwards - the same two-gate shape as the model host check.
    if len(_secret()) < MIN_SECRET_BYTES:
        raise WeakSigningKey(
            f"refusing to sign a token: AUTH_SECRET is "
            f"{len(_secret())} bytes, and at least {MIN_SECRET_BYTES} are "
            f"required. Set AUTH_SECRET in backend/.env."
        )
    body = json.dumps(
        {"u": user_id, "v": TOKEN_VERSION,
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
    # THE HALF THAT MATTERS FOR FORGERY. Verifying with an empty key means any
    # caller can mint a token naming any user id - including one holding the
    # admin capability - because they can compute the signature themselves.
    # None rather than an exception: this function's contract is that it never
    # raises, and None lands the request on `empty_scope()`.
    if len(_secret()) < MIN_SECRET_BYTES:
        return None
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

    #: A host may carry several people (one office, one NAT, one browser per
    #: family member), so its budget is a MULTIPLE of the per-email one rather
    #: than the same number. It exists to bound work, not to identify anyone:
    #: without it a caller cycling a fresh address per request never filled any
    #: bucket, and every request reached a 64 MiB Argon2 verify.
    HOST_MULTIPLIER = 4
    #: A failure budget limits work over time; this separate ceiling limits
    #: work happening at the same instant. Four Argon2 checks are about
    #: 256 MiB with the configured profile, while an unbounded burst could
    #: exhaust the machine before any request had finished and been counted.
    MAX_IN_FLIGHT_PER_HOST = 4

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        #: Keys whose bucket has already been recorded as full. The audit row
        #: is owed once per fill, not once per refusal - see `record_failure`.
        self._audited: set[str] = set()
        self._in_flight: dict[str, int] = {}
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

    def _limit_for(self, key: str) -> int:
        return (settings.auth_max_attempts * self.HOST_MULTIPLIER
                if key.startswith("host:") else settings.auth_max_attempts)

    def check(self, key: str, now: float) -> int | None:
        """Seconds to wait, rounded up, or None to proceed."""
        window = settings.auth_lockout_seconds
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < window]
            self._fails[key] = recent
            if not recent:
                # The window emptied, so the next fill owes a fresh audit row.
                self._audited.discard(key)
            if len(recent) >= self._limit_for(key):
                remaining = window - (now - recent[0])
                buckets = max(1, math.ceil(remaining / self.GRANULARITY))
                return buckets * self.GRANULARITY
        return None

    def record_failure(self, key: str, now: float) -> bool:
        """Record a failure. True only on the attempt that FILLS the bucket.

        The caller writes the `rate_limited` audit row on that True and on no
        other, so the durable record still says the lockout happened while the
        refusal path itself stops being an unauthenticated write. `login` used
        to write a row on EVERY refusal, which made the locked-out branch the
        cheapest path to an INSERT - no Argon2 work at all - against the same
        SQLite file ingestion is writing to. That is the denial-of-service
        primitive this class's own docstring says it exists to avoid, and the
        row carried up to 200 bytes of caller-chosen text in `actor_username`.
        """
        with self._lock:
            self._fails.setdefault(key, []).append(now)
            window = settings.auth_lockout_seconds
            recent = [t for t in self._fails[key] if now - t < window]
            self._fails[key] = recent
            if len(recent) < self._limit_for(key) or key in self._audited:
                return False
            self._audited.add(key)
            return True

    def reserve_work(self, host: str) -> bool:
        """Atomically reserve one expensive password check for a host."""
        with self._lock:
            active = self._in_flight.get(host, 0)
            if active >= self.MAX_IN_FLIGHT_PER_HOST:
                return False
            self._in_flight[host] = active + 1
            return True

    def release_work(self, host: str) -> None:
        """Release a reservation even when verification raised."""
        with self._lock:
            active = self._in_flight.get(host, 0)
            if active <= 1:
                self._in_flight.pop(host, None)
            else:
                self._in_flight[host] = active - 1

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._audited.discard(key)


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
                       (at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, 'session', NULL, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 user_id, username[:200], action, outcome, detail),
            )
    except Exception:  # noqa: BLE001 - an unwritable audit must not block login
        pass


# ------------------------------------------------------------------ the login


def login(email: str, password: str, now: float | None = None,
          *, client_host: str | None = None) -> dict:
    """Verify credentials and issue a token. Raises AuthError on refusal.

    ONE failure message for every credential failure. "No such user" and
    "wrong password" are the same sentence and the same amount of work - see
    _DUMMY_HASH - because the pair of them is a user enumeration oracle.

    TWO BUCKETS. The email bucket is keyed on a value THE CALLER CHOOSES, so
    on its own it bounded nothing: a fresh address per request met an empty
    bucket every time and every request reached a 64 MiB Argon2 verify
    (argon2-cffi's RFC_9106_LOW_MEMORY profile - time_cost 3, memory_cost
    65536 KiB, parallelism 4). Twenty in flight is about 1.3 GB on a machine
    that is also running local inference. The host bucket is what bounds the
    work; the email bucket is what protects one account.

    `client_host` is optional so every existing caller keeps working; when it
    is absent only the email bucket applies, and the route passes it.
    """
    now = time.time() if now is None else now
    key = (email or "").strip().lower()
    host_key = f"host:{client_host}" if client_host else None
    work_key = client_host or "unknown-client"

    # The host bucket is checked FIRST and refuses before any hashing, which
    # is the whole point of having it.
    for bucket in ([host_key] if host_key else []) + [key]:
        wait = _limiter.check(bucket, now)
        if wait is not None:
            # NO AUDIT ROW HERE. It was written on the way past by the attempt
            # that filled the bucket; one per refusal turned this branch into
            # an unauthenticated writer at request rate.
            raise AuthError(
                "rate_limited",
                f"Too many failed attempts. Try again in {wait} seconds.",
                retry_after=wait,
            )

    # Reserve BEFORE Argon2. Checking the historical failure bucket above is
    # insufficient for a burst: many requests can all observe an empty bucket
    # before the first expensive hash finishes and records its failure.
    if not _limiter.reserve_work(work_key):
        raise AuthError(
            "rate_limited",
            "Too many sign-in checks are already running. Try again shortly.",
            retry_after=_Limiter.GRANULARITY,
        )

    try:
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
    finally:
        _limiter.release_work(work_key)

    # An inactive user is refused with the SAME message. Saying "your account
    # is disabled" confirms the address exists.
    if not ok or row is None or not row["is_active"]:
        filled = _limiter.record_failure(key, now)
        if host_key and _limiter.record_failure(host_key, now):
            filled = True
        _audit("login_failed", "denied", key,
               user_id=row["id"] if row else None)
        if filled:
            # Once per bucket-fill, so the lockout is still on the durable
            # record without the refusal path writing a row per request.
            _audit("login_failed", "rate_limited", key)
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    _limiter.clear(key)
    if host_key:
        # A successful login clears the host budget too: the traffic was
        # legitimate, and leaving it charged would lock out the next person
        # behind the same address.
        _limiter.clear(host_key)
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
        "SELECT id FROM users WHERE id = ? AND is_active = 1", (user_id,)
    ).fetchone()
    return row["id"] if row else None


def announce_mode() -> None:
    """Say, once at startup, whether anybody has to log in.

    THIS LINE EXISTS BECAUSE ITS ABSENCE COST TWO DAYS. `env_file` used to be a
    relative path, so a server launched from the repository root ignored
    `backend/.env` entirely and came up with authentication OFF while that file
    said `demo_required`. Nothing said so. The only way to discover it was to
    call /api/auth/me, see `required: false`, and know what that meant - and in
    the meantime a browser showed "Authentication disabled" beside a
    configuration file that had switched it on.

    It is a log line and NOT a field on /api/health, deliberately. That surface
    was narrowed on purpose - it is the one unauthenticated route, and whether
    this deployment demands credentials is exactly the kind of fact an
    unauthenticated caller should not be handed. The operator starting the
    process can read the terminal; a stranger on the port cannot.

    The secret is reported as PRESENT OR ABSENT and never printed, not even
    truncated. A prefix is enough to confirm a guess.

    Logged through `uvicorn.error`, NOT through the "rag_intelligence" logger. That one is
    a rotating FILE handler, attached lazily the first time `errors._log()`
    runs - so at startup it has no handler at all and a record sent to it is
    dropped silently. A startup line nobody sees is the defect this function
    was written to prevent, appearing one level up; the first version of it did
    exactly that and was caught by looking for the line rather than assuming
    it. `uvicorn.error` is the logger that prints "Application startup
    complete", so this lands in the same stream the operator is already
    watching.
    """
    from .access import AUTH_DISABLED

    log = logging.getLogger("uvicorn.error")
    if settings.auth_mode == AUTH_DISABLED:
        log.warning(
            "AUTH_MODE=%s - every request sees every document, and no login is "
            "required. Set AUTH_MODE=demo_required in backend/.env to enforce "
            "access control.", settings.auth_mode)
        return
    secret = (settings.auth_secret or "").strip()
    log.info(
        "AUTH_MODE=%s - a bearer token is required; AUTH_SECRET %s",
        settings.auth_mode,
        f"present ({len(secret)} chars)" if secret else "ABSENT",
    )


def install() -> None:
    """The only wiring. Called once from `lifespan`."""
    from . import access

    check_secret_or_refuse()
    announce_mode()
    access.set_user_resolver(resolve_user_id)
