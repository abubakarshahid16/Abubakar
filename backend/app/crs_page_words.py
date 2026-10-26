"""What the Page/Section cell says (order 228.4).

A row with a datasheet page keeps "p.1 - Corrosion allowance (V-2001)". A row with NO
page and no value read - one that was looked for and not found - used to print the field and every
equipment tag of its group ("Rated capacity (PSV-1, PSV-2, ... 40 tags)", over 300
characters). It now says where the engineer should know it was NOT found, and the tags are
cut to three and a count:

    "Not found on pages 1-5 - Rated capacity (PSV-1, PSV-2, PSV-3 and 37 more)"

The range is the submittal's own page count (its `pages` table); unknown: "Not found on the
datasheet". Display only; a finding's wording and verdict are not touched.
"""

from __future__ import annotations

from .db import connect

#: At most this many tags are named in the cell; the rest are counted.
MAX_TAGS = 3


def _page_count(document_id: str | None) -> int:
    if not document_id:
        return 0
    row = (
        connect()
        .execute(
            "SELECT COUNT(*) AS n FROM pages WHERE document_id = ?", (document_id,)
        )
        .fetchone()
    )
    return int(row["n"]) if row else 0


def _tags(tags: list[str]) -> str:
    shown = tags[:MAX_TAGS]
    more = len(tags) - len(shown)
    return f" ({', '.join(shown)}{f' and {more} more' if more else ''})" if tags else ""


def where(
    pages: list[int],
    page_text: str,
    field: str,
    tags: list[str],
    document_id: str | None,
    read: bool,
) -> str:
    """The Page/Section text. With pages, or with a value that was read but has no page
    recorded: `page_text` ("p.1-2"), the field and the tags, as before. With nothing read
    (`read` False, no page): "Not found on pages 1-N", the field and at most three tags."""
    if pages or read or not (field or tags):
        text = f"{page_text} - {field}" if field and page_text else page_text or field
        return text + (f" ({', '.join(tags)})" if tags else "")
    total = _page_count(document_id)
    lead = (
        f"Not found on pages 1-{total}"
        if total > 1
        else "Not found on page 1"
        if total == 1
        else "Not found on the datasheet"
    )
    return f"{lead} - {field}{_tags(tags)}" if field else lead + _tags(tags)
