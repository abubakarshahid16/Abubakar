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
