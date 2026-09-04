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


def require_document(document_id: str) -> dict:
    """404 on an unknown id, so GET agrees with POST."""
    row = connect().execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
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
