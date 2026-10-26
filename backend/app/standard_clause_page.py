"""The page of a standard that holds a clause a checklist item cites (order 225).

A checklist item cites its source as a label and a clause ("API 520-I", "3.26").
The finding it writes used to carry that text and nothing to open: no standard
document, no page, so an engineer could not go from the row to the clause. This
finds both, from the standard's own page text (OCR text included):

  * the standard is the one of the run's applicable standards that carries that
    label (`standard_ids.same_standard`, the rule the checklist's own matching
    uses), so a caller can only be pointed at what the run already read;
  * the page is the ONE page where the clause number opens a heading line of the
    dotted shape, not counting contents pages (their lines end in a page number).

Anything else is "not located", never a guess: no such standard in the run, the
clause on no page, or on more than one page that is not a contents page.
Read only; no network.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import paragraph_ids, standard_ids
from .config import settings
from .db import connect

#: A heading line's trailing page number: a contents entry, not a heading.
_CONTENTS_TAIL = re.compile(r"(?:\.{2,}|\s{2,}|\s)\d{1,4}\s*$")
_DOTTED = paragraph_ids.SHAPES["dotted"]


def _standard_of(run_id: str, label: str) -> str | None:
    """The run's applicable standard that is `label`, or None; two are None."""
    rows = (
        connect()
        .execute(
            "SELECT d.id, d.filename, c.document_number, c.title"
            " FROM review_applicable_standards a JOIN documents d ON d.id = a.standard_document_id"
            " LEFT JOIN document_classification c ON c.document_id = d.id"
            " WHERE a.review_run_id = ?",
            (run_id,),
        )
        .fetchall()
    )
    found = {
        r["id"]
        for r in rows
        if any(
            standard_ids.same_standard(label, name)
            for name in (r["filename"], r["document_number"], r["title"])
            if name
        )
    }
    return next(iter(found)) if len(found) == 1 else None


def _opens_heading(lines: list[str], at: int, clause: str) -> bool:
    """Does `clause` open a heading at line `at`? Its title on the same line, or
    (OCR keeps them apart) the number alone and the title on the next line. A
    title that ends in a page number is a contents entry, not a heading."""
    m = _DOTTED.match(lines[at])
    if m and m.group("id") == clause:
        return not _CONTENTS_TAIL.search(m.group("rest"))
    following = lines[at + 1] if at + 1 < len(lines) else ""
    alone = re.fullmatch(rf"{re.escape(clause)}\.?", lines[at])
    return bool(
        alone
        and re.match(r"[A-Za-z]", following)
        and not _CONTENTS_TAIL.search(following)
    )


def _pages_with(text_of_pages: list[tuple[int, str]], clause: str) -> set[int]:
    """The pages where `clause` opens a heading line."""
    pages: set[int] = set()
    for number, text in text_of_pages:
        lines = [ln.strip() for ln in (text or "").splitlines()]
        if any(_opens_heading(lines, at, clause) for at in range(len(lines))):
            pages.add(number)
    return pages


@lru_cache(maxsize=512)
def _page_of(standard: str, clause: str, signature: tuple) -> int | None:
    """`signature` (page count, text size, db) is only the cache key: a changed standard is a new key."""
    del signature
    rows = (
        connect()
        .execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (standard,),
        )
        .fetchall()
    )
    pages = _pages_with([(r["page_no"], r["text"] or "") for r in rows], clause)
    return next(iter(pages)) if len(pages) == 1 else None


def locate(
    run_id: str, label: str | None, clause: str | None
) -> tuple[str | None, int | None]:
    """(standard document id, page) for a checklist item's source, or
    (None, None): nothing is stored for a standard or a clause not located."""
    clause = (clause or "").strip().rstrip(".")
    if not label or not clause:
        return None, None
    standard = _standard_of(run_id, label)
    if standard is None:
        return None, None
    size = (
        connect()
        .execute(
            "SELECT count(*) AS n, coalesce(sum(length(text)), 0) AS c FROM pages WHERE document_id = ?",
            (standard,),
        )
        .fetchone()
    )
    page = _page_of(standard, clause, (size["n"], size["c"], str(settings.db_path)))
    return (standard, page) if page else (None, None)


def attach(run_id: str, findings: list[dict]) -> None:
    """Set `standard_document_id` and `standard_page` on each written checklist
    finding whose cited clause is located (in the database and in place); a
    finding whose standard or clause is not located is left exactly as it was."""
    conn = connect()
    for finding in findings:
        label, _, clause = (finding.get("standard_clause") or "").rpartition(" ")
        standard, page = locate(run_id, label, clause)
        if standard and page:
            with conn:
                conn.execute(
                    "UPDATE review_findings SET standard_document_id = ?, standard_page = ? WHERE id = ?",
                    (standard, page, finding["id"]),
                )
            finding["standard_document_id"], finding["standard_page"] = standard, page
