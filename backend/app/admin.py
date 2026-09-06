"""Administration: users, disciplines and document grants.

Implements `docs/design-admin-screen.md`, which was written BEFORE these routes
on purpose. Where this module had to decide something the contract did not
state, the decision is written down here rather than left in the diff.

WHAT THIS MODULE REFUSES TO DO
------------------------------

  * It never accepts or returns a PASSWORD. There is no parameter for one and
    no branch that would write `users.password_hash` from client input. A new
    user gets a hash of a random value nobody ever sees, so the account exists
    and cannot be signed into until the setup token is redeemed. That is a
    stronger guarantee than a rule saying "do not send passwords": there is no
    code path that could.

  * It never returns a setup token twice. The token is generated, returned
    once, and only its SHA-256 is stored. `GET /api/admin/users` has no column
    for it and the storage has no plaintext to return even if a route asked.

  * It never answers 403. A caller who is not an admin gets exactly what a
    caller asking for a route that does not exist gets - 404, same body, same
    shape. A 403 would confirm both that the admin surface is here and that
    the caller found it, which is the one fact the check exists to withhold.

WHERE REVOCATION TAKES EFFECT
-----------------------------

`revoke_grant` deletes the `document_role_access` row and that is the entire
invalidation, because THERE IS NO CACHED SCOPE to invalidate:
`access.current_scope` calls `access.scope_for_user` on every request, which
runs the grant-table join every time (see the module docstring in access.py -
it refuses to cache a scope in module state). So the document leaves that
user's search results on their NEXT REQUEST, not their next login, and it does
so without this module knowing anything about sessions.

If a scope cache is ever added, `revoke_grant` is where it must be invalidated,
and `test_revoke_is_visible_on_the_next_request` is the test that will go red
if it is not.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import auth as auth_mod
from . import errors
from .config import settings
from .db import connect

# ------------------------------------------------------------- error codes
#
# `errors.safe_error` coerces a code it does not recognise to `internal`, so a
# code that is not registered here would reach the client as "the server
# crashed" - which is precisely the failure errors.py exists to prevent, and
# the UI switches on these five names. They are added to the existing sets
# rather than edited into errors.py because that file is not this change's to
# own; the equivalent edit to errors.py is in this change's report.

EMAIL_IN_USE = "email_in_use"
UNKNOWN_DISCIPLINE = "unknown_discipline"
INVALID_EMAIL = "invalid_email"
CANNOT_DEACTIVATE_SELF = "cannot_deactivate_self"
UNKNOWN_DOCUMENT = "unknown_document"

ADMIN_ERROR_CODES = frozenset(
    {EMAIL_IN_USE, UNKNOWN_DISCIPLINE, INVALID_EMAIL,
     CANNOT_DEACTIVATE_SELF, UNKNOWN_DOCUMENT}
)
errors.CLIENT_ERROR_CODES = errors.CLIENT_ERROR_CODES | ADMIN_ERROR_CODES
errors.ALL_CODES = errors.ALL_CODES | ADMIN_ERROR_CODES

#: `admin` is a CAPABILITY, not a discipline - the contract's first section.
#: It is a row in `roles` like any other, which is why the schema needed no
#: `users.is_admin` column: a person is IT *and* admin by holding two roles,
#: and modelling it as a column would have made the two mutually exclusive at
#: exactly the point somebody wanted both.
ADMIN_ROLE = "admin"

#: 24 hours, from the contract. Single-use is enforced by `redeemed_at`; the
#: redemption ROUTE is deliberately not built here - see the report's gaps.
SETUP_TOKEN_TTL_SECONDS = 24 * 60 * 60

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


# ------------------------------------------------------------------ storage


def ensure_schema() -> None:
    """Create the setup-token table if it is not there yet.

    A separate table rather than columns on `users`, for two reasons that are
    the same reason: a token is not an attribute of a person. It is issued,
    it expires, it is redeemed once and then it is dead weight - and a NULL
    `setup_token_hash` on every long-established user would be a column that
    is meaningless for almost every row.

    ONLY THE HASH IS STORED. A stolen database yields no usable token, and
    "shown once" is a property of the storage rather than a promise made by
    the route that returns it.

    This lives here and not in `db.py` because the schema file is owned by
    another change in flight; `keyword.ensure_schema()` sets the precedent for
    a module carrying its own table. The equivalent `db.py` diff is in the
    report, and moving it there changes nothing about this module: the
    statement is `IF NOT EXISTS`.
    """
    conn = connect()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_setup_tokens (
                   user_id     TEXT PRIMARY KEY
                                 REFERENCES users(id) ON DELETE CASCADE,
                   token_sha256 TEXT NOT NULL,
                   created_at  TEXT NOT NULL,
                   expires_at  TEXT NOT NULL,
                   redeemed_at TEXT
               )"""
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(value: str | None) -> str | None:
    """`2026-09-05T18:12:04Z`, or None.

    NULL SURVIVES AS NULL. The contract is explicit that a user who has never
    signed in renders as nothing, and the only way a UI can render nothing is
    to be handed nothing - a "never", a dash or an epoch here would put the
    decision in the backend and the placeholder on the screen.
    """
    if not value:
        return None
    return value.replace("+00:00", "Z") if value.endswith("+00:00") else value


def _audit(action: str, actor: dict | None, resource_type: str,
           resource_id: str | None, outcome: str = "ok",
           detail: str | None = None) -> None:
    """Durable record of an administrative change.

    `detail` carries ids and role names only. Never an email body, a document
    title or a token - the audit table is the one most likely to be exported.
    """
    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO audit_events
                       (at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (_now(), (actor or {}).get("id"),
                 ((actor or {}).get("email") or "unauthenticated")[:200],
                 action, resource_type, resource_id, outcome, detail),
            )
    except Exception:  # noqa: BLE001 - an unwritable audit must not block the change
        pass


# ------------------------------------------------------------- the guard


def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status,
                         detail=errors.safe_error(code, message))


def _not_found() -> HTTPException:
    """The ONLY refusal an admin route ever makes about authorisation.

    Identical in status, code and message to an unknown id, so a probe cannot
    tell an admin route it may not use from a route that is not there.
    """
    return _fail(404, errors.NOT_FOUND, "not found")


def _role_names_of(user_id: str) -> list[str]:
    return [r["name"] for r in connect().execute(
        """SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id
           WHERE ur.user_id = ? ORDER BY r.name""", (user_id,))]


def is_admin(user_id: str) -> bool:
    return ADMIN_ROLE in _role_names_of(user_id)


def current_admin(request: Request) -> dict | None:
    """The admin making this request, or a 404 that says nothing.

    Identity is resolved by `auth.resolve_user_id` and by nothing else, so the
    admin surface uses the same one-way boundary as the rest of the API: the
    client says who it is, the server decides what that means. Note that
    `resolve_user_id` re-reads `is_active`, so a deactivated admin loses the
    admin screen on their next request rather than at token expiry.

    THE ONE CONCESSION, stated rather than hidden: under `AUTH_MODE=disabled`
    a caller who presents no identity at all is allowed through. Under that
    mode `access.unrestricted_scope()` already hands every caller every
    document, so an admin screen that were *stricter* than the document routes
    would protect nothing while making the screen impossible to open in the
    default development mode. A caller who DOES identify is still checked -
    a non-admin with a token is 404 in both modes, which is what makes the
    contract's first test meaningful under either setting.
    """
    user_id = auth_mod.resolve_user_id(request)
    if user_id is None:
        from .access import AUTH_DISABLED

        if settings.auth_mode == AUTH_DISABLED:
            return None
        raise _not_found()
    if not is_admin(user_id):
        raise _not_found()
    row = connect().execute("SELECT id, email FROM users WHERE id = ?",
                            (user_id,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------- request bodies
#
# Request models live here rather than in `schemas.py`, which carries response
# models. They are validated the same way either place; the split keeps the
# generated client's response types in one file.


class CreateUserRequest(BaseModel):
    email: str = Field(examples=["new@example.com"])
    disciplines: list[str] = Field(default_factory=list)
    is_admin: bool = False


class GrantRequest(BaseModel):
    document_id: str = Field(examples=["doc_626b1a92bf6d"])
    discipline: str = Field(examples=["Civil Engineering"])


# ------------------------------------------------------------ disciplines


def _discipline_rows() -> list[dict]:
    """Every role that is not the admin capability.

    DERIVED, not a constant. A hard-coded list of four names here would be a
    second source of truth about what a discipline is, disagreeing with the
    `roles` table the moment anybody added one - and disagreeing shapes either
    side of a boundary is the exact defect this contract was written to stop.
    Roles are created by `scripts/seed_access.py --roles`; this screen assigns
    them and does not duplicate their creation.
    """
    return [dict(r) for r in connect().execute(
        "SELECT id, name FROM roles WHERE name != ? ORDER BY name",
        (ADMIN_ROLE,))]


def _resolve_discipline(name: str) -> dict:
    """The role row for a discipline name, or 422.

    Case- and space-insensitive on the way in: refusing `civil engineering`
    while accepting `Civil Engineering` is a trap for a caller, not a safety
    property. The name is echoed back in its CANONICAL spelling so the UI
    never has two labels for one discipline.
    """
    wanted = (name or "").strip().lower()
    for row in _discipline_rows():
        if row["name"].lower() == wanted:
            return row
    raise _fail(422, UNKNOWN_DISCIPLINE, f"no such discipline: {name!r}")


def list_disciplines() -> dict:
    conn = connect()
    out = []
    for row in _discipline_rows():
        users = conn.execute(
            "SELECT COUNT(*) AS n FROM user_roles WHERE role_id = ?",
            (row["id"],)).fetchone()["n"]
        docs = conn.execute(
            "SELECT COUNT(*) AS n FROM document_role_access "
            "WHERE role_id = ? AND permission = 'read'",
            (row["id"],)).fetchone()["n"]
        out.append({
            "name": row["name"],
            "user_count": users,
            "document_count": docs,
            # Everyone in this discipline sees an empty corpus. That reads as
            # broken search, which is why it is surfaced rather than inferred
            # from a zero the reader has to notice.
            "warning": "no_documents" if docs == 0 else None,
        })
    return {"disciplines": out}


# ------------------------------------------------------------------ users


def list_users() -> dict:
    conn = connect()
    users = []
    for row in conn.execute(
            "SELECT id, email, is_active, created_at, last_login_at "
            "FROM users ORDER BY email"):
        roles = _role_names_of(row["id"])
        disciplines = [r for r in roles if r != ADMIN_ROLE]
        users.append({
            "user_id": row["id"],
            "email": row["email"],
            "disciplines": disciplines,
            "is_admin": ADMIN_ROLE in roles,
            "active": bool(row["is_active"]),
            "created_at": _iso(row["created_at"]),
            "last_login_at": _iso(row["last_login_at"]),
            # An ENUM, never a sentence. The UI switches on it and owns the
            # wording; a message built here would be a string the frontend had
            # to parse for meaning, and would need a frontend change to
            # translate.
            "warning": "no_discipline" if not disciplines else None,
        })
    # There is no `setup_token` key in this shape, and no query above reads
    # `user_setup_tokens`. That is what "shown once" means here.
    return {"users": users}


def _new_user_id(conn) -> str:
    """`usr_` + 8 hex, per the contract's examples, and proven unique.

    The retry is not decoration: an id chosen at random is unique until it is
    not, and the alternative to checking is an INSERT that fails in front of a
    live request.
    """
    for _ in range(20):
        candidate = f"usr_{secrets.token_hex(4)}"
        if conn.execute("SELECT 1 FROM users WHERE id = ?",
                        (candidate,)).fetchone() is None:
            return candidate
    raise _fail(500, errors.INTERNAL, "could not allocate a user id")


def create_user(body: CreateUserRequest, actor: dict | None) -> dict:
    """Create a user and issue a one-time setup token.

    EVERY VALIDATION HAPPENS BEFORE THE FIRST WRITE. A user created and then
    refused a discipline is the "seeded but useless" state the screen exists
    to make visible, and creating it while reporting a failure would be the
    worst possible combination.
    """
    ensure_schema()
    conn = connect()

    email = (body.email or "").strip()
    if not _EMAIL.match(email) or len(email) > 320:
        # The address is NOT echoed. A 422 handler in this project echoed a
        # submitted body back into a log once already.
        raise _fail(422, INVALID_EMAIL, "that is not a valid email address")
    email = email.lower()

    if conn.execute("SELECT 1 FROM users WHERE lower(email) = ?",
                    (email,)).fetchone():
        raise _fail(409, EMAIL_IN_USE, "a user with that email already exists")

    roles = [_resolve_discipline(name) for name in body.disciplines]
    if body.is_admin:
        row = conn.execute("SELECT id, name FROM roles WHERE name = ?",
                           (ADMIN_ROLE,)).fetchone()
        if row is None:
            # The capability has no row to grant. Refused rather than created
            # here: this screen assigns roles, `seed_access.py --roles` makes
            # them, and two places creating roles is two definitions of what a
            # role is.
            raise _fail(422, UNKNOWN_DISCIPLINE,
                        "the admin capability role does not exist; "
                        "run scripts/seed_access.py --roles")
        roles.append(dict(row))

    user_id = _new_user_id(conn)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc)
               + timedelta(seconds=SETUP_TOKEN_TTL_SECONDS))
    now = _now()

    with conn:
        conn.execute(
            """INSERT INTO users (id, email, display_name, password_hash,
                                  is_active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (user_id, email, email.split("@")[0],
             # A REAL Argon2 hash of a value that is generated here, never
             # stored and never returned. The account therefore exists and is
             # unusable until the token is redeemed. `password_hash` is NOT
             # NULL, so a placeholder was needed; an empty string or a fixed
             # sentinel would be a hash every such account SHARED, and the day
             # somebody's password verified against it they would all be open.
             auth_mod._hasher.hash(secrets.token_urlsafe(32)), now),
        )
        for role in roles:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at, "
                "granted_by) VALUES (?, ?, ?, ?)",
                (user_id, role["id"], now, (actor or {}).get("id")),
            )
        conn.execute(
            """INSERT INTO user_setup_tokens
                   (user_id, token_sha256, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, hashlib.sha256(token.encode("utf-8")).hexdigest(), now,
             expires.isoformat(timespec="seconds")),
        )
    _audit("admin_user_created", actor, "user", user_id,
           detail=",".join(r["name"] for r in roles) or None)

    return {
        "user_id": user_id,
        "email": email,
        "setup_token": token,
        "setup_token_expires_at": _iso(expires.isoformat(timespec="seconds")),
        # Not decoration. The UI is required to say this beside the value and
        # not to store it, and a client reading the response should not have
        # to consult a document to learn it.
        "shown_once": True,
    }


def deactivate_user(user_id: str, actor: dict | None) -> dict:
    """Deactivate. NEVER delete.

    Conversations and reports reference a user, and a report's whole value is
    that it says who asked for it. A hard delete would orphan the evidence a
    report depends on, so the account stops working and the record stays.

    Idempotent: deactivating an already-inactive user is a 200. The client
    asked for a state and the state is now true.
    """
    if actor is not None and user_id == actor.get("id"):
        # Without this the last admin can lock every user, including
        # themselves, out of a system whose only other door is a terminal.
        raise _fail(409, CANNOT_DEACTIVATE_SELF,
                    "an admin cannot deactivate their own account")

    conn = connect()
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        raise _not_found()
    with conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    _audit("admin_user_deactivated", actor, "user", user_id)
    # `auth.resolve_user_id` re-reads is_active on every request, so this takes
    # effect on the user's NEXT request rather than at token expiry.
    return {"user_id": user_id, "active": False}


# ----------------------------------------------------------------- grants


def list_grants() -> dict:
    conn = connect()
    documents = []
    for row in conn.execute(
            "SELECT id, filename FROM documents ORDER BY filename, id"):
        names = [r["name"] for r in conn.execute(
            """SELECT r.name FROM roles r
               JOIN document_role_access dra ON dra.role_id = r.id
               WHERE dra.document_id = ? AND dra.permission = 'read'
                 AND r.name != ?
               ORDER BY r.name""", (row["id"], ADMIN_ROLE))]
        documents.append({
            "document_id": row["id"],
            "filename": row["filename"],
            "disciplines": names,
            # A document nobody can see is invisible in every search and looks
            # exactly like a broken upload. Deny-by-default is correct and this
            # is its cost, so the cost is displayed.
            "warning": None if names else "no_discipline_can_see_this",
        })
    return {"documents": documents}


def _require_document(document_id: str) -> dict:
    row = connect().execute("SELECT id FROM documents WHERE id = ?",
                            (document_id,)).fetchone()
    if row is None:
        raise _fail(404, UNKNOWN_DOCUMENT, "no document with that id")
    return dict(row)


def grant(body: GrantRequest, actor: dict | None) -> dict:
    """Grant read access. IDEMPOTENT.

    `INSERT OR IGNORE` against the (document, role, permission) primary key, so
    a UI retrying a click that timed out cannot double-grant and cannot fail.
    """
    _require_document(body.document_id)
    role = _resolve_discipline(body.discipline)
    conn = connect()
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO document_role_access
                   (document_id, role_id, permission, granted_at, granted_by)
               VALUES (?, ?, 'read', ?, ?)""",
            (body.document_id, role["id"], _now(), (actor or {}).get("id")),
        )
    _audit("admin_grant", actor, "document", body.document_id,
           detail=role["name"])
    return {"document_id": body.document_id, "discipline": role["name"],
            "granted": True}


def revoke_grant(body: GrantRequest, actor: dict | None) -> dict:
    """Revoke read access. IDEMPOTENT, and effective on the next request.

    THIS DELETE IS THE CACHE INVALIDATION. `access.scope_for_user` re-runs the
    grant-table join on every request and holds nothing between them, so
    removing the row removes the document from that user's search results the
    next time they ask - not at their next login. If a scope cache is ever
    introduced, its invalidation belongs on the line below this comment.

    Revoking a grant that does not exist is a 200. The client asked for a
    state; the state is now true, and an error would tell it to retry
    something that is already done.
    """
    _require_document(body.document_id)
    role = _resolve_discipline(body.discipline)
    conn = connect()
    with conn:
        conn.execute(
            "DELETE FROM document_role_access "
            "WHERE document_id = ? AND role_id = ? AND permission = 'read'",
            (body.document_id, role["id"]),
        )
    _audit("admin_revoke", actor, "document", body.document_id,
           detail=role["name"])
    return {"document_id": body.document_id, "discipline": role["name"],
            "granted": False}
