"""What the Page/Section cell says (order 228.4).

A row with a datasheet page keeps "p.1 - Corrosion allowance (V-2001)". A row with NO
page and no value read - one that was looked for and not found - used to print the field and every
equipment tag of its group ("Rated capacity (PSV-1, PSV-2, ... 40 tags)", over 300
characters). It now says that no value was read from the datasheet (not that the sheet lacks it: a value may
be there under a label the check did not search for), and the tags are cut to three and a count:

    "Not read from the datasheet (5 pages) - Rated capacity (PSV-1, PSV-2, PSV-3 and 37 more)"

The count is the submittal's own (`documents.page_count`, else its `pages` rows), stated as
the size of the document, never as "pages searched"; unknown: "Not read from the datasheet";
several documents in one group: "Not read from the datasheets". Display only; a finding's
wording and verdict are not touched.
"""

from __future__ import annotations

import sqlite3

from . import field_links
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


def read_pages(document_ids: set[str | None], label: str) -> tuple[list[int], bool]:
    """(pages, exact): where a non-blank value was read, anywhere on the submittal, under this field's name
    (order 307: a row must never say "not read" about a field the reader did read). Names are compared as the
    pairing compares them (`field_links.canonical`). `exact` False = no exact name, but every word of the
    row's name is inside a read name of two words or more ("viscosity relieving" in "viscosity at relieving
    temper."): a probable match, said as one."""
    documents = sorted(d for d in document_ids if d)
    want = field_links.canonical(label)
    if not documents or not want:
        return [], True
    marks = ",".join("?" * len(documents))
    try:
        rows = (
            connect()
            .execute(
                "SELECT field_name, field_label, page FROM submittal_facts"
                f" WHERE submittal_document_id IN ({marks}) AND superseded_at IS NULL AND is_blank = 0"
                " AND page IS NOT NULL",
                documents,
            )
            .fetchall()
        )
    except (
        sqlite3.OperationalError
    ):  # no review tables yet: nothing was read, so nothing to point at
        return [], True
    exact: set[int] = set()
    probable: set[int] = set()
    words = set(want.split())
    for r in rows:
        names = [
            field_links.canonical(r["field_name"]),
            field_links.canonical(r["field_label"]),
        ]
        if want in names:
            exact.add(r["page"])
        elif len(words) >= 2 and any(words <= set(n.split()) for n in names if n):
            probable.add(r["page"])
    return (sorted(exact), True) if exact else (sorted(probable), False)


def _pages_words(pages: list[int]) -> str:
    return f"page{'s' if len(pages) > 1 else ''} " + ", ".join(str(p) for p in pages)


def where(
    pages: list[int],
    page_text: str,
    field: str,
    tags: list[str],
    document_ids: set[str | None],
    read: bool,
    label: str = "",
) -> str:
    """The Page/Section text. With pages, or with a value that was read but has no page
    recorded: `page_text` ("p.1-2"), the field and the tags, as before. With nothing read
    (`read` False, no page): "Not read from the datasheet (9 pages)", the field and at most
    three tags. It states the document's own page count, never that those pages were
    searched (an unread page is said by the row's own text); a group that spans several
    documents says "the datasheets" and no count."""
    if pages or read or not (field or tags):
        text = f"{page_text} - {field}" if field and page_text else page_text or field
        return text + (f" ({', '.join(tags)})" if tags else "")
    elsewhere, exact = read_pages(document_ids, label)
    if elsewhere:
        # a value WAS read, just not tied to this row's tags: never "not read" (order 307)
        what = "A value" if exact else "A value that may be this field"
        return (
            f"{field}: {what} was read on {_pages_words(elsewhere)}, "
            f"not tied to this row{_tags(tags)}; engineer to confirm"
        )
    documents = {d for d in document_ids if d}
    total = _page_count(next(iter(documents))) if len(documents) == 1 else 0
    lead = (
        "Not read from the datasheets"
        if len(documents) > 1
        else f"Not read from the datasheet ({total} page{'s' if total > 1 else ''})"
        if total
        else "Not read from the datasheet"
    )
    return f"{lead} - {field}{_tags(tags)}" if field else lead + _tags(tags)
