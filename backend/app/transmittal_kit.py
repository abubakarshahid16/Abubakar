"""#1482 TRANSMITTAL KIT: what a transmittal states, and whether it agrees with what is held.

For a submittal whose kind is `transmittal` (switch `settings.transmittal_kit_enabled`, OFF by
default) the transmittal's OWN stored pages and tables are read by code - no model, no socket:

  1. header fields (transmittal no., date, from, to, purpose of issue): a blank or absent one is a
     "not stated" row;
  2. the table of listed documents (document no., title, revision, sheets), read by one general
     table reader (a header row names the columns; text tables and `pages.tables_json` alike);
  3. each listed document HELD in the caller's allowed documents (its number is in the held
     document's own title block, `classification.title_block_lines`): the listed revision against
     the revision on the held cover, the listed sheet count against its page count; a difference
     is a row with both values and pages;
  4. a REQUIRED-SUBMISSIONS LIST named at run time by `settings.transmittal_required_list_document_ids`
     (document ids, comma separated). It is CLIENT DATA: read from the local DB at run time only,
     never copied anywhere. Its items are read by the same general table reader (a table whose
     header has a type/title/description/deliverable column), one quote per item. Required items
     the transmittal does not list, and listed items the list does not ask for, are rows. Not
     named: one note, nothing else.

Only documents in the caller's allowed ids are read (rule 5). Every row is NEEDS_ENGINEER_REVIEW;
nothing is ever a Pass or Compliant, and a count states its boundary.
"""

from __future__ import annotations

import json
import logging
import re

from . import procedure_text, spec_kit
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

KIND = "transmittal"
CODE = "spec_kit_transmittal"
NOTE_CODE = spec_kit.NOT_RUN

_HEADER_FIELDS = (
    ("number", "transmittal number", r"transmittal\s*(?:no|number|num|#)"),
    ("date", "date", r"date(?:\s+of\s+issue)?"),
    ("from", "from", r"from"),
    ("to", "to", r"to"),
    (
        "purpose",
        "purpose of issue",
        r"purpose(?:\s+of\s+(?:issue|transmittal))?|issued\s+for",
    ),
)
_ROLES = (
    (
        "docno",
        r"\bdoc(?:ument)?\.?\s*(?:no|number|num|#)\b|\bdrawing\s*(?:no|number)\b",
    ),
    ("rev", r"\brev(?:ision)?\b"),
    ("sheets", r"\bsheets?\b|\bpages?\b"),
    ("due", r"\bdue\b|\bdate\b|\bsubmi"),
    ("title", r"title|description|type|deliverable|\bname\b|\bdocument\b"),
)
_GAP = re.compile(r"\s{2,}|\t")
_RULE_CELL = re.compile(r":?-{3,}:?")
_REV = re.compile(
    r"\brev(?:ision)?(?![a-z])\.?\s*(?:(?:no|nr|num|number)\b\.?\s*)?[:\-]?\s*([A-Za-z0-9]{1,4})\b",
    re.I,
)
# a word a revision LABEL is printed with ("Rev No", "Revision By"): never a revision value
_REV_LABEL = frozenset(
    {
        "no",
        "nr",
        "num",
        "by",
        "date",
        "desc",
        "rev",
        "for",
        "of",
        "the",
        "and",
        "chk",
        "app",
    }
)
_QUOTE = 300
_TRAIL_DATE = re.compile(r"\s(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})$")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _row(
    item: str, requirement: str, finding: str, detail: str, page, quote, source=None
) -> dict:
    """`source`: (document, page, quote) of ANOTHER document the row cites - stored as the
    finding's requirement source (document, page, text), never as the transmittal's page."""
    return {
        "item": item,
        "requirement": requirement,
        "finding": finding,
        "rationale": f"{CODE}: {detail}; not a verdict, engineer to confirm",
        "page": page,
        "quote": (quote or "")[:_QUOTE] or None,
        "clause": None,
        "source": source,
    }


def _note(item: str, text: str) -> dict:
    return {
        "item": f"note:{item}",
        "requirement": "The transmittal kit ran.",
        "finding": text + "; engineer to check.",
        "rationale": f"{NOTE_CODE}: {text}",
        "page": None,
        "quote": None,
        "clause": None,
    }


# ---------------------------------------------------------------- reading


def _cells(line: str) -> list[str]:
    """One text line's cells. A line with a '|' is a pipe-delimited row (text extracted or
    converted as a pipe table): split at every '|', the empty edges of a leading or trailing
    '|' dropped and an empty interior cell KEPT, so a blank value stays in its column. Any
    other line splits at wide gaps (two or more spaces, or a tab)."""
    stripped = line.strip()
    if "|" in stripped:
        parts = [" ".join(c.split()) for c in stripped.split("|")]
        if stripped.startswith("|"):
            parts = parts[1:]
        if stripped.endswith("|") and parts:
            parts = parts[:-1]
        return parts if any(parts) else []
    return [c.strip() for c in _GAP.split(stripped) if c.strip()]


def _grids(
    document_id: str, pages: list[tuple[int, str]]
) -> list[tuple[int, list[tuple[list[str], str]]]]:
    """(page, [(cells, quote)]) per table: stored `tables_json` grids, else blocks of
    consecutive page lines that split into two or more cells at wide gaps."""
    out = []
    stored = {
        r["page_no"]: r["tables_json"]
        for r in connect().execute(
            "SELECT page_no, tables_json FROM pages WHERE document_id = ?",
            (document_id,),
        )
    }
    for page_no, text in pages:
        try:
            tables = json.loads(stored.get(page_no) or "{}").get("tables") or []
        except (ValueError, AttributeError):
            tables = []
        for table in tables:
            grid = [
                [" ".join(str(c or "").split()) for c in row]
                for row in table.get("rows") or []
            ]
            if grid:
                out.append((page_no, [(row, " | ".join(row)) for row in grid]))
        block: list[tuple[list[str], str]] = []
        for line in [*text.splitlines(), ""]:
            cells = _cells(line)
            if cells and all(_RULE_CELL.fullmatch(c) for c in cells if c):
                continue  # a "|---|---|" rule line under a pipe table's header row
            if cells and (m := _TRAIL_DATE.search(cells[-1])) and m.start() > 0:
                cells[-1:] = [cells[-1][: m.start()].strip(), m.group(1)]
            if len(cells) >= 2:
                block.append((cells, " ".join(line.split())))
            else:
                if len(block) >= 2:
                    out.append((page_no, block))
                block = []
    return out


def _roles(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for i, cell in enumerate(header):
        for role, pattern in _ROLES:
            if re.search(pattern, cell.lower()):
                found.setdefault(role, i)
                break
    return found


def _read_tables(document_id: str, pages, needs, forbids=()) -> list[dict]:
    """Rows of every table whose header row has all the `needs` roles and none of `forbids`:
    {page, quote, cells: {role: value}}. A row must be as wide as the widest column used."""
    rows = []
    for page_no, grid in _grids(document_id, pages):
        for h, (header, _q) in enumerate(grid):
            roles = _roles(header)
            if not all(r in roles for r in needs) or any(r in roles for r in forbids):
                continue
            for cells, quote in grid[h + 1 :]:
                if len(cells) <= max(roles.values()):
                    break
                rows.append(
                    {
                        "page": page_no,
                        "quote": quote,
                        "cells": {r: cells[i] for r, i in roles.items()},
                    }
                )
            break
    return rows


def header_fields(
    pages: list[tuple[int, str]],
) -> dict[str, tuple[str, int | None, str | None]]:
    """field -> (value, page, quote); value is "" for a blank label and the field is absent from
    the result when no label line was found."""
    found = {}
    for key, _label, pattern in _HEADER_FIELDS:
        rx = re.compile(rf"^\s*(?:{pattern})\s*[:\-]\s*(.*)$", re.I)
        cell = re.compile(rf"(?:{pattern})\s*[.:#\-]?", re.I)
        for page_no, text in pages:
            hit = next(
                (
                    (value, ln)
                    for ln in text.splitlines()
                    if (value := _label_value(ln, rx, cell)) is not None
                ),
                None,
            )
            if hit:
                found[key] = (hit[0], page_no, " ".join(hit[1].split()))
                break
    return found


_LABEL_CELL = re.compile(
    "(?:"
    + "|".join(f"(?:{p})" for _k, _l, p in _HEADER_FIELDS)
    + "|"
    + "|".join(f"(?:{p})" for _r, p in _ROLES)
    + r"|no|item|s/?n|qty|remarks?|status)\s*[.:#\-]?",
    re.I,
)


def _label_like(cell: str) -> bool:
    """A cell that is only a field label or a column name ('Date', 'Document No.', 'Rev')."""
    return bool(cell) and bool(_LABEL_CELL.fullmatch(cell.strip()))


def _label_value(line: str, rx: re.Pattern, cell: re.Pattern) -> str | None:
    """The value of a 'Label: value' line, or of a pipe row whose first cell is the label
    alone ('| Label | value |'); "" for a label with no value, None when not a label line.
    A pipe row of three or more label-like cells is a table's HEADER row, not label:value,
    and a value cell that is itself a label is no value (#1482 review)."""
    if m := rx.match(line):
        return m.group(1).strip()
    if "|" in line:
        cells = _cells(line)
        if not cells or not cell.fullmatch(cells[0]):
            return None
        if sum(_label_like(c) for c in cells) >= 3:
            return None
        value = cells[1] if len(cells) > 1 else ""
        return "" if _label_like(value) else value
    return None


def header_rows(pages) -> list[dict]:
    got = header_fields(pages)
    rows = []
    for key, label, _p in _HEADER_FIELDS:
        value, page, quote = got.get(key, ("", None, None))
        if value:
            continue
        where = (
            f"the label is on page {page} with no value"
            if page
            else "no such label found"
        )
        rows.append(
            _row(
                f"header:{key}",
                f"The transmittal states its {label}.",
                f"{label.capitalize()}: not stated on the transmittal ({where}); engineer to check.",
                f"{label} not stated ({where})",
                page,
                quote,
            )
        )
    return rows


# ---------------------------------------------------------------- held documents


def _first_pages(scope: list[str]) -> dict[str, str]:
    out = {}
    conn = connect()
    for i in range(0, len(scope), 500):
        part = scope[i : i + 500]
        marks = ",".join("?" * len(part))
        for r in conn.execute(
            f"SELECT document_id, text FROM pages WHERE page_no = 1 AND document_id IN ({marks})",
            part,
        ):
            out[r["document_id"]] = r["text"] or ""
    return out


def _has_number(text: str, number: str) -> bool:
    want = _norm(number)
    return bool(want) and any(
        _norm(tok) == want for tok in re.split(r"[\s:;,()]+", text)
    )


def holders(
    numbers: list[str], candidates: list[str], excluded: list[str] | None = None
) -> dict[str, list[str]]:
    """number -> the candidate documents whose OWN title block carries it. Page 1 is a cheap
    first filter; the title block (`classification.title_block_lines`) decides. A document
    routed as a transmittal (confirmed or suggested) LISTS numbers and is never a holder; one
    that carried a listed number is added to `excluded`, so the run can say so."""
    from .classification import title_block_lines

    first = _first_pages(candidates)
    out: dict[str, list[str]] = {n: [] for n in numbers}
    for doc in candidates:
        wanted = [n for n in numbers if _has_number(first.get(doc, ""), n)]
        if not wanted:
            continue
        if (
            procedure_text.document_kind(doc) == KIND
        ):  # #1482: it lists, it does not hold
            if excluded is not None:
                excluded.append(doc)
            continue
        pages = [{"page_no": p, "text": t} for p, t in procedure_text.load_pages(doc)]
        block = title_block_lines(pages)
        for n in wanted:
            if any(
                _has_number(line, n) and not _OTHER_REF.search(line)
                for _p, line in block
            ):
                out[n].append(doc)
    return out


def _rev_value(line: str) -> str | None:
    """The first revision VALUE on a line; a label word after 'Rev' ("Rev No", "Revision
    By", the "Rev" of "Revision: Rev 2") is not one, and the search goes on from it."""
    pos = 0
    while m := _REV.search(line, pos):
        if m.group(1).lower() not in _REV_LABEL:
            return m.group(1)
        pos = m.start(1)
    return None


def _one_revision(lines) -> tuple[str, int, str] | bool | None:
    """The one revision these lines state: lines that name ANOTHER document (supersedes,
    reference ...) are skipped; two different values (a revision history) = False, unsure."""
    found = []
    for page_no, line in lines:
        if _OTHER_REF.search(line):
            continue
        if value := _rev_value(line):
            found.append((value, page_no, " ".join(line.split())))
    values = {f[0].lower().lstrip("0") or "0" for f in found}
    if len(values) > 1:
        return False
    return found[0] if found else None


def cover_revision(document_id: str) -> tuple[str, int, str] | None:
    """The revision on the held document's title block, else on its first page (the cover).
    Several different revisions where one is looked for = none read (never a guess)."""
    from .classification import title_block_lines

    loaded = procedure_text.load_pages(document_id)
    pages = [{"page_no": p, "text": t} for p, t in loaded]
    block = title_block_lines(pages)
    got = _one_revision(block)
    if got is None:
        seen = set(block)
        got = _one_revision(
            (p, ln)
            for p, t in loaded[:1]
            for ln in t.splitlines()
            if (p, ln) not in seen
        )
    return got or None


def _same_rev(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or (a.isdigit() and b.isdigit() and int(a) == int(b))


def _int(text: str | None) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,4})\s*", text or "")
    return int(m.group(1)) if m else None


def _page_count(document_id: str) -> int | None:
    row = (
        connect()
        .execute("SELECT page_count FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    return row[0] if row and row[0] else None


def listed_rows(listed: list[dict], held: dict[str, list[str]]) -> list[dict]:
    rows = []
    for entry in listed:
        c = entry["cells"]
        number = c["docno"]
        docs = held.get(number, [])
        if len(docs) != 1:
            if len(docs) > 1:
                rows.append(
                    _row(
                        f"ambiguous:{number}",
                        f"Listed document {number} is one held document.",
                        f"{number}: more than one held document carries this number "
                        f"in its title block ({len(docs)}); nothing compared; engineer to check.",
                        f"{number} held {len(docs)} times, nothing compared",
                        entry["page"],
                        entry["quote"],
                    )
                )
            continue
        doc = docs[0]
        cover = cover_revision(doc)
        listed_rev = c.get("rev", "").strip()
        if listed_rev and cover is None:
            rows.append(
                _row(
                    f"revision:{number}",
                    f"The revision listed for {number} is the held document's.",
                    f"{number}: listed revision {listed_rev} (transmittal page {entry['page']}); "
                    f"no revision read from the held document's cover; engineer to check.",
                    f"{number} listed revision {listed_rev}, none read from the cover",
                    entry["page"],
                    entry["quote"],
                )
            )
        elif listed_rev and not _same_rev(listed_rev, cover[0]):
            rows.append(
                _row(
                    f"revision:{number}",
                    f"The revision listed for {number} is the held document's.",
                    f"{number}: listed revision {listed_rev} (transmittal page {entry['page']}), "
                    f"held document {doc} cover states revision {cover[0]} (page {cover[1]}); "
                    f"engineer to resolve.",
                    f'{number} listed {listed_rev}, cover says {cover[0]}: "{cover[2]}"',
                    entry["page"],
                    entry["quote"],
                )
            )
        sheets, pages = _int(c.get("sheets")), _page_count(doc)
        if sheets is not None and pages is not None and sheets != pages:
            rows.append(
                _row(
                    f"sheets:{number}",
                    f"The sheet count listed for {number} is the held document's.",
                    f"{number}: listed {sheets} sheets (transmittal page {entry['page']}), "
                    f"held document {doc} has {pages} pages; engineer to resolve.",
                    f"{number} listed {sheets} sheets, held document has {pages} pages",
                    entry["page"],
                    entry["quote"],
                )
            )
    return rows


# ---------------------------------------------------------------- the required list


def required_items(list_ids: list[str]) -> list[dict]:
    """{item, due, page, quote, document} per row of a table whose header names a type, title,
    description or deliverable column. One general reader; nothing about a layout."""
    out = []
    for doc in list_ids:
        pages = procedure_text.load_pages(doc)
        text = {p: _fold(t) for p, t in pages}
        for r in _read_tables(doc, pages, ("title",), forbids=("rev",)):
            item = r["cells"]["title"].strip()
            if item and not item.isdigit():
                # the citation is checked on the list page's own stored text: the row as
                # read, else (a stored grid row joined with '|') the item's own cell
                on_page = text.get(r["page"], "")
                cite = next(
                    (q for q in (r["quote"], item) if q and _fold(q) in on_page), None
                )
                out.append(
                    {
                        "item": item,
                        "due": r["cells"].get("due", ""),
                        "page": r["page"],
                        "quote": r["quote"],
                        "document": doc,
                        "cite": cite,
                    }
                )
    return out


def _fold(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


_GENERIC = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "of",
        "the",
        "to",
        "in",
        "on",
        "report",
        "reports",
        "datasheet",
        "datasheets",
        "data",
        "sheet",
        "sheets",
        "document",
        "documents",
        "drawing",
        "drawings",
        "calculation",
        "calculations",
        "list",
        "schedule",
        "submission",
        "submissions",
        "drg",
        "dwg",
        "doc",
    }
)
_STOP = frozenset({"a", "an", "and", "for", "of", "the", "to", "in", "on", "with"})
_OTHER_REF = re.compile(
    r"supersed|replac|cancel|reference|\bref\b|\bsee\b|related", re.I
)


def _content(text: str) -> frozenset[str]:
    return _words(text) - _GENERIC


def _covers(required: dict, entry: dict) -> bool:
    """A listed document covers a required item only when every word of the item except stop
    words (the, of, for ...) is in the listed title - type words such as datasheet or report
    count, so 'Pump datasheet' needs both. Extra words on the listed side are ignored. An item
    of generic words only, a document number or a generic title never covers; unsure = not."""
    need = _words(required["item"]) - _STOP
    # an item of generic words only ("Datasheet") says nothing specific: never covered
    return bool(need - _GENERIC) and need <= _words(entry["cells"].get("title", ""))


def _exact(required: dict, entry: dict) -> bool:
    return _words(required["item"]) == _words(entry["cells"].get("title", ""))


def _coverage(items: list[dict], listed: list[dict]) -> dict[int, int | None]:
    """item index -> index of the ONE listed document that covers it. A listed document that
    covers more than one item covers them only where the words match exactly."""
    taken: dict[int, int] = {}
    out: dict[int, int | None] = {}
    for i, req in enumerate(items):
        out[i] = None
        for j, e in enumerate(listed):
            if _covers(req, e) and (j not in taken or _exact(req, e)):
                out[i] = j
                taken.setdefault(j, i)
                break
    return out


def required_rows(items: list[dict], listed: list[dict], boundary: str) -> list[dict]:
    rows = []
    cover = _coverage(items, listed)
    for i, req in enumerate(items):
        if cover[i] is not None:
            continue
        key = " ".join(sorted(_words(req["item"]), key=req["item"].lower().find))
        due = f"; due {req['due']}" if req["due"] else ""
        # #1482: the quote is the LIST's text - never the transmittal's page and evidence. It
        # is CITED (document, page, text) only when it was found on that list page's text;
        # otherwise the list page is only named.
        verified = bool(req.get("cite"))
        where = (
            f"required-submissions list {req['document']} page {req['page']}"
            if verified
            else f"named on required-submissions list {req['document']} page "
            f"{req['page']}; quote not verified on that page"
        )
        rows.append(
            _row(
                f"not_transmitted:{key}",
                f"The required item '{req['item']}' is transmitted.",
                f"Required item '{req['item']}'{due} ({where}) is not on this transmittal: "
                f"not transmitted - engineer to confirm whether due. {boundary}",
                f"required item not listed on the transmittal ({where})",
                None,
                None,
                source=(req["document"], req["page"], req["cite"])
                if verified
                else None,
            )
        )
    used = set(cover.values())
    for j, e in enumerate(listed):
        if j in used or any(_covers(r, e) for r in items):
            continue
        rows.append(
            _row(
                f"extra:{e['cells']['docno']}",
                f"The listed document {e['cells']['docno']} is on the required-submissions list.",
                f"{e['cells']['docno']} {e['cells'].get('title', '')} (transmittal page "
                f"{e['page']}) is listed but not on the required-submissions list; engineer "
                f"to check. {boundary}",
                f'listed item not on the required list: "{e["quote"]}"',
                e["page"],
                e["quote"],
            )
        )
    return rows


# ---------------------------------------------------------------- the run


def applies(document_id: str | None) -> bool:
    return bool(
        settings.transmittal_kit_enabled
        and document_id
        and procedure_text.document_kind(document_id) == KIND
    )


def _named_ids() -> list[str]:
    raw = settings.transmittal_required_list_document_ids or ""
    return [i.strip() for i in raw.split(",") if i.strip()]


def _held_notes(numbers: list[str], held: dict, excluded: list[str]) -> list[dict]:
    notes = []
    unmatched = [n for n in numbers if not held.get(n)]
    if unmatched:
        notes.append(
            _note(
                "not_held",
                f"{len(unmatched)} of {len(numbers)} listed documents were not found among the documents you may read (matched by document number in the held document's title block; documents routed as transmittals are never taken as the held document); revision and sheets not compared for them",
            )
        )
    if excluded:
        notes.append(
            _note(
                "transmittal_not_holder",
                f"{len(excluded)} document(s) you may read carry a listed number on page 1 but are routed as transmittals (confirmed or suggested), so they were not taken as the held document",
            )
        )
    return notes


def rows_for(document_id: str, scope: frozenset[str]) -> list[dict]:
    pages = procedure_text.load_pages(document_id)
    if not any(text.strip() for _, text in pages):
        return [
            _note(
                "no_text",
                "Transmittal kit not run: no page text is stored for the transmittal",
            )
        ]
    rows = header_rows(pages)
    table = [
        r
        for r in _read_tables(document_id, pages, ("docno",))
        if any(c in r["cells"] for c in ("rev", "sheets"))
    ]
    listed = [r for r in table if re.search(r"\d", r["cells"]["docno"])]
    if len(table) > len(listed):
        rows.append(
            _note(
                "no_number",
                f"{len(table) - len(listed)} of {len(table)} rows of the listed-documents table "
                "carry no document number; not compared with held documents or the required list",
            )
        )
    if not listed:
        rows.append(
            _note(
                "no_table",
                "No table of listed documents (document number with revision or sheets) was read from the transmittal",
            )
        )
    named = _named_ids()
    allowed = [i for i in named if i in scope]
    blocked = len(named) - len(allowed)
    skip = {document_id, *named}
    candidates = sorted(scope - skip)
    numbers = sorted({e["cells"]["docno"] for e in listed})
    excluded: list[str] = []
    held = holders(numbers, candidates, excluded) if numbers else {}
    rows += listed_rows(listed, held)
    rows += _held_notes(numbers, held, excluded)
    if blocked:
        rows.append(
            _note(
                "list_not_allowed",
                f"{blocked} of {len(named)} named required-submissions list documents are not in the documents you may read; not read",
            )
        )
    if not named:
        rows.append(
            _note(
                "no_list",
                "Transmittal kit: no required-submissions list named; required and extra items not checked",
            )
        )
    elif allowed:
        items = required_items(allowed)
        if items:
            boundary = (
                f"({len(items)} required items read from {len(allowed)} named list "
                f"document(s); {len(listed)} documents listed on this transmittal only.)"
            )
            rows += required_rows(items, listed, boundary)
        else:
            rows.append(
                _note(
                    "list_no_items",
                    "No table of required items was read from the named required-submissions list; required and extra items not checked",
                )
            )
    return rows


def for_review(review_run_id: str, scope: frozenset[str]) -> None:
    """The review job's call, after the comparison. A failure never fails the review."""
    try:
        row = (
            connect()
            .execute(
                "SELECT submittal_document_id FROM review_runs WHERE id = ?",
                (review_run_id,),
            )
            .fetchone()
        )
        doc = row[0] if row else None
        if applies(doc):
            spec_kit._store(review_run_id, doc, rows_for(doc, scope))
    except Exception as exc:  # noqa: BLE001 - the kit is optional; the review stands
        log.warning("transmittal kit skipped: %s", type(exc).__name__)
