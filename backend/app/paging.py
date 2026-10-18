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
