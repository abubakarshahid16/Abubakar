"""Shared API validation.

Three failures the audit found, all of the same shape - the API accepting
something meaningless and answering as though it were fine:

  * GET returned `200 []` for an unknown document id, indistinguishable from a
    real document with no chunks, while POST on the same id correctly 404'd.
  * An unbounded `limit` returned the entire table, and a very large one
    reached SQLite and produced a 500.
  * Unknown query parameters were silently ignored, so a client that
    mistyped a filter believed it had filtered when it had not.

A client must never be able to believe it asked something it did not.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from . import access, errors
from .db import connect

#: Hard ceiling on any page size. Without one, `limit=999999` returns
#: everything and `limit=-1` returned the whole table.
MAX_LIMIT = 200
DEFAULT_LIMIT = 20

RETRIEVABLE_VALUES = ("true", "false", "all")


def require_document(document_id: str, scope=None) -> dict:
    """404 on an unknown id, so GET agrees with POST.

    AND 404 - not 403 - on a document the caller may not read. A document
    somebody is not allowed to see must be INDISTINGUISHABLE from one that does
    not exist: same status, same message, same shape. A 403 where an unknown id
    returns 404 is an existence oracle, and it leaks the one fact the grant was
    protecting - that the document is real.

    `scope` is optional only so that internal callers which have already
    resolved authorisation are not forced to re-derive it. Every ROUTE passes
    one; a route that forgets is the failure this signature makes visible in
    review rather than at runtime.
    """
    row = connect().execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is not None and scope is not None and not scope.may_read(document_id):
        row = None      # fall through to the identical not-found path below
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(
                errors.NOT_FOUND, "no document with that id", document_id=document_id
            ),
        )
    return dict(row)


def reject_unknown_params(request: Request, allowed: set[str]) -> None:
    """422 on any query parameter this endpoint does not understand."""
    unknown = sorted(set(request.query_params.keys()) - allowed)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.UNKNOWN_PARAMETER,
                f"unknown query parameter(s): {', '.join(unknown)}",
            ) | {"allowed": sorted(allowed)},
        )


def validate_retrievable(value: str) -> str:
    """Case-insensitive: rejecting `TRUE` while accepting `true` is a trap for
    a caller, not a safety property."""
    value = (value or "").strip().lower()
    if value not in RETRIEVABLE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER, "retrievable must be one of: true, false, all"
            ),
        )
    return value


def retrievable_clause(value: str) -> str:
    return {
        "true": " AND retrievable = 1",
        "false": " AND retrievable = 0",
        "all": "",
    }[value]


def _require_identity_to_write(scope: access.AccessScope) -> None:
    """A conversation nobody owns is one nobody can ever read again.

    Under `demo_required` a caller with no identity resolves to an empty scope,
    and every READ correctly returns nothing. A WRITE that succeeded would
    manufacture an orphan - the same shape as #79 on uploads - so it is refused
    with the same 401 /api/auth/me gives, rather than accepted into a void.
    """
    if scope.unrestricted or scope.user_id:
        return
    raise HTTPException(
        status_code=401,
        detail=errors.safe_error(errors.UNAUTHENTICATED, "sign in to continue"),
    )


def _require_named_reviewer(scope: access.AccessScope, what: str) -> None:
    """A decision nobody signed is not a decision - the rule the finding route
    applies to a confirmation."""
    _require_identity_to_write(scope)
    if scope.user_id is None:
        raise HTTPException(
            status_code=401,
            detail=errors.safe_error(
                errors.UNAUTHENTICATED, f"{what} must name the person who did it"
            ),
        )


def _deliverable_visible(item: dict, scope: access.AccessScope) -> bool:
    """May this caller touch this deliverable? (r2 S3)

    A deliverable tied to a document follows that document's grant. One with NO
    document used to be open to every identified caller, including one with no
    grant at all; it now needs the admin capability or at least one grant.
    """
    document_id = item.get("document_id")
    if document_id:
        return scope.may_read(document_id)
    return scope.is_admin or bool(scope.allowed_document_ids)


def _actor_from_scope(scope: access.AccessScope) -> dict | None:
    """Who to name in the audit trail for an ENGINEER'S action.

    `admin.current_admin` is the wrong dependency for these: it is a GATE as
    well as a lookup, and a non-admin gets its deliberately silent 404. That
    is right for the admin surface and wrong for an engineer's own work - it
    made recording a final review code (section 15, an engineer's action)
    impossible for anyone but an admin, and said "not found" while doing it.
    This resolves the name without deciding anything about permission; the
    route's own scope has already done that.
    """
    if not scope.user_id:
        return None
    row = (
        connect()
        .execute("SELECT id, email FROM users WHERE id = ?", (scope.user_id,))
        .fetchone()
    )
    return dict(row) if row else {"id": scope.user_id}
