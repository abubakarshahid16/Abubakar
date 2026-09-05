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

from . import errors
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
