"""Order 117 item 5: the fields every paged list response carries.

`total` is the denominator of the page (CLAUDE.md rule 4): every item the
caller may read under the same filter, whatever page was asked for. A list
that is cut without saying how many it left out is a silent loss.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ListPage(BaseModel):
    total: int = Field(
        description="every item the caller may read under the same filter, "
        "whatever page was asked for: the denominator of this page"
    )
    limit: int | None = Field(None, description="the page size; null means every item")
    offset: int = 0


#: the header a bare-list route states its total in (order 117 item 5)
TOTAL_HEADER = "X-Total-Count"


def page_of(rows: list, limit: int | None, offset: int, response) -> list:
    """One page of a route that answers with a bare JSON list, which a body
    field cannot be added to without breaking its readers. The total goes in
    `X-Total-Count`, always, so even an unpaged answer states its count;
    `limit=None` is every row from `offset` on."""
    response.headers[TOTAL_HEADER] = str(len(rows))
    return rows[offset:] if limit is None else rows[offset : offset + limit]


def page_body(key: str, rows: list, limit: int | None, offset: int) -> dict:
    """One page of a list held in memory, as a `ListPage` body under `key`:
    the rows of the page, `total` (every row) and the page asked for."""
    page = rows[offset:] if limit is None else rows[offset : offset + limit]
    return {key: page, "total": len(rows), "limit": limit, "offset": offset}


def limit_param(maximum: int = 1000):
    """The optional page size every paged list takes; omitted means every row."""
    from fastapi import Query

    return Query(None, ge=1, le=maximum, description="page size; omit for every row")


def offset_param():
    from fastapi import Query

    return Query(0, ge=0)
