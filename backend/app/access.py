"""Request-scoped authorisation. Computed once, server-side, per request.

WHAT THIS MODULE REFUSES TO DO, and why each refusal is load-bearing:

  * It never reads a SCOPE from anything the client sends. Identity may come
    from the request - that is what a bearer token is - but the set of
    documents that identity may see is derived server-side from the grant
    tables and from nothing else. The distinction is the whole design: a
    client can claim who it is, and the server decides what that means.
    Anything the client could write, the client could widen.

  * It never caches a scope in module state. A module-level dict or a mutable
    default keyed by "current user" is shared across concurrent requests, and
    under two simultaneous requests from different roles it hands one of them
    the other's documents. That is a confidentiality failure that no test of a
    single request can see, which is why `test_two_concurrent_requests_never_
    share_scope` exists and why it runs them genuinely in parallel.

  * It never defaults to "everything". `AccessScope` has no default
    constructor argument. A scope must be built by a function that names where
    it came from - `scope_for_user` from the grant tables, or
    `unrestricted_scope` which says in its own name that it is not restricting
    anything.

DENY BY DEFAULT is a property of the schema (there is no row meaning
"everyone"), so this module cannot accidentally widen a scope: the only way to
see a document is a `document_role_access` row reachable through `user_roles`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .config import settings
from .db import connect

#: Authentication is not wired into the routes yet, and every existing test
#: runs with it off. `disabled` must therefore keep behaving exactly as the
#: system did before this module existed - which is also what makes the
#: rollback a config change rather than a revert.
AUTH_DISABLED = "disabled"
AUTH_REQUIRED = "demo_required"

@dataclass(frozen=True, slots=True)
class AccessScope:
    """What one request is allowed to see. Immutable, and never global.

    `allowed_document_ids` is the whole authorisation decision, resolved before
    any retrieval runs. Frozen so a downstream caller cannot widen it: a
    mutable set passed through five layers is a set that eventually gets
    `.update()` called on it by something trying to be helpful.
    """

    user_id: str | None
    allowed_document_ids: frozenset[str]
    #: True only for the unauthenticated development mode. Recorded so a route
    #: or a test can assert which kind of scope it is holding rather than
    #: inferring it from the size of the id set.
    unrestricted: bool = False
    def may_read(self, document_id: str) -> bool:
        return document_id in self.allowed_document_ids

    def owns_conversation(self, owner_user_id: str | None) -> bool:
        """Whether this caller may use a conversation on any route.

        Auth-disabled development remains unrestricted. In required mode an
        identified user owns only rows stamped with that exact identity.
        Legacy NULL-owner rows fail closed until an explicit migration assigns
        them; an unidentified caller owns nothing.
        """
        if self.unrestricted:
            return True
        if self.user_id is None:
            return False
        return owner_user_id == self.user_id

    def conversation_filter(self) -> tuple[str | None, bool] | None:
        """Return the SQL-list equivalent of :meth:`owns_conversation`."""
        if self.unrestricted:
            return None
        return (self.user_id, False)


def unrestricted_scope() -> AccessScope:
    """Every document. Named so it can never be reached by accident.

    Used when AUTH_MODE is `disabled`, which is the default and what every
    pre-existing test runs under. It is a real scope object rather than a
    `None` meaning "no filtering", so the enforcement path is IDENTICAL in both
    modes - the filter always runs, and only its contents differ. A `None`
    short-circuit would mean the enforced path was never exercised by the
    tests that run with auth off, which is most of them.
    """
    ids = frozenset(r["id"] for r in connect().execute("SELECT id FROM documents"))
    return AccessScope(user_id=None, allowed_document_ids=ids, unrestricted=True)


def scope_for_user(user_id: str) -> AccessScope:
    """Everything `user_id` may read, from the grant tables alone.

    One query, deliberately. A fallback branch in Python - "if the join
    returned nothing, try X" - is where a deny-by-default schema turns into an
    allow-by-accident system.
    """
    conn = connect()
    ids = frozenset(
        r["document_id"]
        for r in conn.execute(
            """SELECT DISTINCT dra.document_id
               FROM user_roles ur
               JOIN document_role_access dra ON dra.role_id = ur.role_id
               WHERE ur.user_id = ? AND dra.permission = 'read'""",
            (user_id,),
        )
    )
    return AccessScope(user_id=user_id, allowed_document_ids=ids)


def empty_scope(user_id: str | None = None) -> AccessScope:
    """Sees nothing. The correct answer for an unidentified caller when
    AUTH_MODE requires identity - not an error, and not everything."""
    return AccessScope(user_id=user_id, allowed_document_ids=frozenset())


# --------------------------------------------------------------- the hook

#: How a request's identity is resolved, injected rather than imported.
#:
#: Login does not exist yet and is deliberately not built here: it is the easy
#: part, and it is the part that would make this feature feel finished while
#: the enforcement was still untested. Tests install their own resolver, which
#: is also how the concurrency test drives two different users at once.
_resolve_user_id = None


def set_user_resolver(fn) -> None:
    """Install the identity resolver. Called by the auth layer, or by a test."""
    global _resolve_user_id
    _resolve_user_id = fn


def current_scope(request: Request) -> AccessScope:
    """The scope for THIS request. The single place a scope is created.

    Every route depends on this and nothing builds an AccessScope any other
    way, so there is exactly one line in the system where "what may this
    request see" is decided.

    The resolver is handed the Request because that is where identity lives -
    a bearer token, a session cookie - and reading it per request is what makes
    the scope request-local by construction. Note the distinction that matters:
    IDENTITY comes from the request, and the SCOPE is then derived server-side
    from the grant tables. A client can claim who it is; it can never state
    what it may see.
    """
    if settings.auth_mode == AUTH_DISABLED:
        return unrestricted_scope()
    if _resolve_user_id is None:
        return empty_scope()
    user_id = _resolve_user_id(request)
    if not user_id:
        return empty_scope()
    return scope_for_user(user_id)
