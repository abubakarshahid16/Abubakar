"""What the Page/Section cell says (order 228.4).

A row with a datasheet page keeps "p.1 - Corrosion allowance (V-2001)". A row with NO
page and no value read - one that was looked for and not found - used to print the field and every
equipment tag of its group ("Rated capacity (PSV-1, PSV-2, ... 40 tags)", over 300
characters). It now says where the engineer should know it was NOT found, and the tags are
cut to three and a count:

    "Not found on the datasheet (5 pages) - Rated capacity (PSV-1, PSV-2, PSV-3 and 37 more)"

The count is the submittal's own (`documents.page_count`, else its `pages` rows), stated as
the size of the document, never as "pages searched"; unknown: "Not found on the datasheet";
several documents in one group: "Not found on the datasheets". Display only; a finding's
wording and verdict are not touched.
"""

from __future__ import annotations

from .db import connect

#: At most this many tags are named in the cell; the rest are counted.
MAX_TAGS = 3


def _page_count(document_id: str | None) -> int:
    """The submittal's page count as the document record states it (`documents.page_count`);
    the number of its `pages` rows only when the record has none."""
    if not document_id:
        return 0
    conn = connect()
    row = conn.execute(
        "SELECT page_count FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row and row["page_count"]:
        return int(row["page_count"])
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM pages WHERE document_id = ?", (document_id,)
    ).fetchone()
    return int(rows["n"]) if rows else 0


def _tags(tags: list[str]) -> str:
    shown = tags[:MAX_TAGS]
    more = len(tags) - len(shown)
    return f" ({', '.join(shown)}{f' and {more} more' if more else ''})" if tags else ""


def where(
    pages: list[int],
    page_text: str,
    field: str,
    tags: list[str],
    document_ids: set[str | None],
    read: bool,
) -> str:
    """The Page/Section text. With pages, or with a value that was read but has no page
    recorded: `page_text` ("p.1-2"), the field and the tags, as before. With nothing read
    (`read` False, no page): "Not found on the datasheet (9 pages)", the field and at most
    three tags. It states the document's own page count, never that those pages were
    searched (an unread page is said by the row's own text); a group that spans several
    documents says "the datasheets" and no count."""
    if pages or read or not (field or tags):
        text = f"{page_text} - {field}" if field and page_text else page_text or field
        return text + (f" ({', '.join(tags)})" if tags else "")
    documents = {d for d in document_ids if d}
    total = _page_count(next(iter(documents))) if len(documents) == 1 else 0
    lead = (
        "Not found on the datasheets"
        if len(documents) > 1
        else f"Not found on the datasheet ({total} page{'s' if total > 1 else ''})"
        if total
        else "Not found on the datasheet"
    )
    return f"{lead} - {field}{_tags(tags)}" if field else lead + _tags(tags)
