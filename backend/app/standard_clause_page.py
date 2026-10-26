"""The page of a standard that holds a clause a checklist item cites (order 225).

A checklist item cites its source as a label and a clause ("API 520-I", "3.26").
The finding it writes used to carry that text and nothing to open: no standard
document, no page, so an engineer could not go from the row to the clause. This
finds both, from the standard's own page text (OCR text included):

  * the standard is the one of the run's INCLUDED applicable standards that carries that
    label (`standard_ids.same_standard`, the rule the checklist's own matching
    uses), so a caller can only be pointed at what the run already read;
  * the page is the ONE page where the clause number opens a heading line of the
    dotted shape, not counting contents pages (their lines end in a page number).

Anything else is "not located", never a guess: no such standard in the run, the
clause on no page, or on more than one page that is not a contents page.
Read only; no network.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from . import claims, paragraph_ids, standard_ids
from .config import settings
from .db import connect

#: Contents entries: dot leaders, or a number after a tab or two spaces.
_LEADER_TAIL = re.compile(r"(?:\.{2,}|\t|\s{2,})\s*\d{1,4}\s*$")
#: Any trailing number: counted only for a whole contents PAGE, never for one line.
_ANY_TAIL = re.compile(r"\s\d{1,4}\s*$")
_BARE_NUMBER = re.compile(r"\d{1,4}")
#: A numbered line that is not a heading: its first word is a function word, a
#: modal or a unit ("3.26 shall be used", "3.26 mm", "3.26 in this clause").
_NOT_A_TITLE = frozenset(
    {
        "shall",
        "should",
        "may",
        "must",
        "will",
        "can",
        "could",
        "would",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "to",
        "in",
        "of",
        "and",
        "or",
        "the",
        "a",
        "an",
        "for",
        "with",
        "per",
        "at",
        "by",
        "from",
        "as",
        "if",
        "it",
        "its",
        "that",
        "this",
        "these",
        "those",
        "which",
        "when",
        "where",
        "while",
        "not",
        "no",
        "than",
        "then",
        "also",
        "see",
    }
)
_SHAPES = (paragraph_ids.SHAPES["dotted"], paragraph_ids.SHAPES["annex"])


def _heading_of(line: str) -> tuple[str, str] | None:
    """(clause id, the rest of the line) of a numbered line, else None."""
    for shape in _SHAPES:
        m = shape.match(line)
        if m:
            return m.group("id"), m.group("rest")
    return None


def _is_title(rest: str, clause: str) -> bool:
    """Could `rest` be the title of heading `clause`? A word of three letters or
    more that is no function word and no unit; a whole-number clause also needs a
    capital (a bare page number or a running header is not a heading)."""
    words = rest.split()
    first = re.sub(r"[^A-Za-z]", "", words[0]) if words else ""
    if len(first) < 3 or first.lower() in _NOT_A_TITLE or claims.unit_dimension(first):
        return False
    return "." in clause or rest[:1].isupper()


def _standard_of(run_id: str, label: str) -> str | None:
    """The run's applicable standard that is `label`, or None; two are None."""
    rows = (
        connect()
        .execute(
            "SELECT d.id, d.filename, c.document_number, c.title"
            " FROM review_applicable_standards a JOIN documents d ON d.id = a.standard_document_id"
            " LEFT JOIN document_classification c ON c.document_id = d.id"
            " WHERE a.review_run_id = ? AND a.included = 1",
            (run_id,),
        )
        .fetchall()
    )
    # The file name and the recorded number identify a standard; the TITLE only by the
    # exact flat key, since a supplement's title ("... Supplement to API 520") names the
    # base standard too and `same_standard` would take it for it.
    found = {
        r["id"]
        for r in rows
        if any(
            standard_ids.same_standard(label, name)
            for name in (r["filename"], r["document_number"])
            if name
        )
        or (
            r["title"]
            and standard_ids.flat_key(label) == standard_ids.flat_key(r["title"])
        )
    }
    return next(iter(found)) if len(found) == 1 else None


def _contents_page(lines: list[str]) -> bool:
    """A contents page: most of its numbered lines end in a page number."""
    numbered = [h for h in map(_heading_of, lines) if h]
    ended = sum(1 for _, rest in numbered if _ANY_TAIL.search(" " + rest))
    return len(numbered) >= 5 and ended * 2 >= len(numbered)


def _opens_heading(lines: list[str], at: int, clause: str) -> bool:
    """Does `clause` open a heading at line `at`? Its title on the same line or,
    when OCR keeps them apart, the number alone and the title on the next line. A
    title with dot leaders or a tab-separated page number, or whose page number
    wraps onto the next line, is a contents entry."""
    here = _heading_of(lines[at])
    following = lines[at + 1] if at + 1 < len(lines) else ""
    after = lines[at + 2] if at + 2 < len(lines) else ""
    if here and here[0] == clause:
        title, wrapped = here[1], following
    elif (
        clause == lines[at].rstrip(".")
        and (clause[:1].isalpha() or "." in clause)
        and re.match(r"[A-Za-z]", following)
    ):
        title, wrapped = following, after
    else:
        return False
    return (
        _is_title(title, clause)
        and not _LEADER_TAIL.search(title)
        and not _BARE_NUMBER.fullmatch(wrapped)
    )


_PAGE_NUMBER = re.compile(r"^\d{1,4}$|^\d{1,4}\s+|\s+\d{1,4}$")


def _line_key(line: str) -> str:
    """The line with ONE plain whole number at its start or end folded ("4 API STANDARD",
    "Page 12", "10"); a dotted clause number ("3.26", "5.1 General") is kept as it is."""
    return _PAGE_NUMBER.sub(
        lambda m: "#" + (" " if m.group().endswith(" ") else ""),
        line.lower().strip(),
        count=1,
    )


def _repeated_lines(text_of_pages: list[tuple[int, str]]) -> frozenset[str]:
    """Lines (digits folded) that appear on at least three pages: running headers and
    footers ("4 API STANDARD 520, PART I", "Page 12 of 146"), never headings."""
    seen: dict[str, set[int]] = {}
    for number, text in text_of_pages:
        for line in (ln.strip() for ln in (text or "").splitlines()):
            if line:
                seen.setdefault(_line_key(line), set()).add(number)
    return frozenset(key for key, pages in seen.items() if len(pages) >= 3)


def _pages_with(
    text_of_pages: list[tuple[int, str]],
    clause: str,
    repeated: frozenset[str] | None = None,
) -> set[int]:
    """The pages where `clause` opens a heading line: contents pages and running headers
    left out."""
    if repeated is None:
        repeated = _repeated_lines(text_of_pages)
    pages: set[int] = set()
    for number, text in text_of_pages:
        lines = [ln.strip() for ln in (text or "").splitlines()]
        lines = ["" if _line_key(ln) in repeated else ln for ln in lines]
        if _contents_page(lines):
            continue
        if any(_opens_heading(lines, at, clause) for at in range(len(lines))):
            pages.add(number)
    return pages


@lru_cache(maxsize=64)
def _pages_of(standard: str, signature: tuple) -> tuple:
    """A standard's page texts, read once; `signature` (page count, text size,
    database) is only the cache key: a changed standard is a new key."""
    del signature
    rows = connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (standard,),
    )
    return tuple((r["page_no"], r["text"] or "") for r in rows)


@lru_cache(maxsize=64)
def _running_of(standard: str, signature: tuple) -> frozenset[str]:
    return _repeated_lines(list(_pages_of(standard, signature)))


def _page_of(standard: str, clause: str, signature: tuple) -> int | None:
    pages = _pages_with(
        list(_pages_of(standard, signature)), clause, _running_of(standard, signature)
    )
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
    for finding in findings:
        label, _, clause = (finding.get("standard_clause") or "").rpartition(" ")
        try:
            conn = connect()
            standard, page = locate(run_id, label, clause)
            if standard and page:
                with conn:
                    conn.execute(
                        "UPDATE review_findings SET standard_document_id = ?, standard_page = ? WHERE id = ?",
                        (standard, page, finding["id"]),
                    )
                finding["standard_document_id"], finding["standard_page"] = (
                    standard,
                    page,
                )
        except Exception as exc:  # noqa: BLE001 - a link is optional; the findings are already written
            logging.getLogger(__name__).warning(
                "standard page not attached to finding %s: %s",
                finding.get("id"),
                type(exc).__name__,
            )
