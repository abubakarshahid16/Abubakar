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
    ("purpose", "purpose of issue", r"purpose(?:\s+of\s+(?:issue|transmittal))?|issued\s+for"),
)
_ROLES = (
    ("docno", r"\bdoc(?:ument)?\.?\s*(?:no|number|num|#)\b|\bdrawing\s*(?:no|number)\b"),
    ("rev", r"\brev(?:ision)?\b"),
    ("sheets", r"\bsheets?\b|\bpages?\b"),
    ("due", r"\bdue\b|\bdate\b|\bsubmi"),
    ("title", r"title|description|type|deliverable|\bname\b|\bdocument\b"),
)
_GAP = re.compile(r"\s{2,}|\t")
_REV = re.compile(r"\brev(?:ision)?\.?\s*[:\-]?\s*([A-Za-z0-9]{1,4})\b", re.I)
_QUOTE = 300
_TRAIL_DATE = re.compile(r"\s(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})$")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _row(item: str, requirement: str, finding: str, detail: str, page, quote) -> dict:
    return {
        "item": item,
        "requirement": requirement,
        "finding": finding,
        "rationale": f"{CODE}: {detail}; not a verdict, engineer to confirm",
        "page": page,
        "quote": (quote or "")[:_QUOTE] or None,
        "clause": None,
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


def _grids(document_id: str, pages: list[tuple[int, str]]) -> list[tuple[int, list[tuple[list[str], str]]]]:
    """(page, [(cells, quote)]) per table: stored `tables_json` grids, else blocks of
    consecutive page lines that split into two or more cells at wide gaps."""
    out = []
    stored = {
        r["page_no"]: r["tables_json"]
        for r in connect().execute(
            "SELECT page_no, tables_json FROM pages WHERE document_id = ?", (document_id,)
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
        for line in text.splitlines() + [""]:
            cells = [c.strip() for c in _GAP.split(line.strip()) if c.strip()]
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


def header_fields(pages: list[tuple[int, str]]) -> dict[str, tuple[str, int | None, str | None]]:
    """field -> (value, page, quote); value is "" for a blank label and the field is absent from
    the result when no label line was found."""
    found = {}
    for key, _label, pattern in _HEADER_FIELDS:
        rx = re.compile(rf"^\s*(?:{pattern})\s*[:\-]\s*(.*)$", re.I)
        for page_no, text in pages:
            hit = next(((m, ln) for ln in text.splitlines() if (m := rx.match(ln))), None)
            if hit:
                found[key] = (hit[0].group(1).strip(), page_no, " ".join(hit[1].split()))
                break
    return found


def header_rows(pages) -> list[dict]:
    got = header_fields(pages)
    rows = []
    for key, label, _p in _HEADER_FIELDS:
        value, page, quote = got.get(key, ("", None, None))
        if value:
            continue
        where = f"the label is on page {page} with no value" if page else "no such label found"
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


def holders(numbers: list[str], candidates: list[str]) -> dict[str, list[str]]:
    """number -> the candidate documents whose OWN title block carries it. Page 1 is a cheap
    first filter; the title block (`classification.title_block_lines`) decides."""
    from .classification import title_block_lines

    first = _first_pages(candidates)
    out: dict[str, list[str]] = {n: [] for n in numbers}
    for doc in candidates:
        wanted = [n for n in numbers if _has_number(first.get(doc, ""), n)]
        if not wanted:
            continue
        pages = [{"page_no": p, "text": t} for p, t in procedure_text.load_pages(doc)]
        block = title_block_lines(pages)
        for n in wanted:
            if any(_has_number(line, n) for _p, line in block):
                out[n].append(doc)
    return out


def cover_revision(document_id: str) -> tuple[str, int, str] | None:
    from .classification import title_block_lines

    pages = [{"page_no": p, "text": t} for p, t in procedure_text.load_pages(document_id)]
    for page_no, line in title_block_lines(pages):
        if m := _REV.search(line):
            return m.group(1), page_no, " ".join(line.split())
    return None


def _same_rev(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or (a.isdigit() and b.isdigit() and int(a) == int(b))


def _int(text: str | None) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,4})\s*", text or "")
    return int(m.group(1)) if m else None


def _page_count(document_id: str) -> int | None:
    row = connect().execute(
        "SELECT page_count FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
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
        for r in _read_tables(doc, pages, ("title",), forbids=("rev",)):
            item = r["cells"]["title"].strip()
            if item and not item.isdigit():
                out.append(
                    {
                        "item": item,
                        "due": r["cells"].get("due", ""),
                        "page": r["page"],
                        "quote": r["quote"],
                        "document": doc,
                    }
                )
    return out


def _covers(required: dict, entry: dict) -> bool:
    c = entry["cells"]
    need = _words(required["item"])
    have = _words(c.get("title", "")) | _words(c["docno"])
    return bool(need) and (need <= have or (bool(c.get("title")) and _words(c["title"]) <= need))


def required_rows(items: list[dict], listed: list[dict], boundary: str) -> list[dict]:
    rows = []
    for req in items:
        if any(_covers(req, e) for e in listed):
            continue
        key = " ".join(sorted(_words(req["item"]), key=req["item"].lower().find))
        due = f"; due {req['due']}" if req["due"] else ""
        rows.append(
            _row(
                f"not_transmitted:{key}",
                f"The required item '{req['item']}' is transmitted.",
                f"Required item '{req['item']}'{due} (required-submissions list page "
                f"{req['page']}) is not on this transmittal: not transmitted - engineer to "
                f"confirm whether due. {boundary}",
                f"required item not listed on the transmittal: \"{req['quote']}\"",
                req["page"],
                req["quote"],
            )
        )
    for e in listed:
        if any(_covers(r, e) for r in items):
            continue
        rows.append(
            _row(
                f"extra:{e['cells']['docno']}",
                f"The listed document {e['cells']['docno']} is on the required-submissions list.",
                f"{e['cells']['docno']} {e['cells'].get('title', '')} (transmittal page "
                f"{e['page']}) is listed but not on the required-submissions list; engineer "
                f"to check. {boundary}",
                f"listed item not on the required list: \"{e['quote']}\"",
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


def rows_for(document_id: str, scope: frozenset[str]) -> list[dict]:
    pages = procedure_text.load_pages(document_id)
    if not any(text.strip() for _, text in pages):
        return [_note("no_text", "Transmittal kit not run: no page text is stored for the transmittal")]
    rows = header_rows(pages)
    listed = [
        r
        for r in _read_tables(document_id, pages, ("docno",))
        if any(c in r["cells"] for c in ("rev", "sheets")) and re.search(r"\d", r["cells"]["docno"])
    ]
    if not listed:
        rows.append(_note("no_table", "No table of listed documents (document number with revision or sheets) was read from the transmittal"))
    named = _named_ids()
    allowed = [i for i in named if i in scope]
    blocked = len(named) - len(allowed)
    skip = {document_id, *named}
    candidates = sorted(scope - skip)
    numbers = sorted({e["cells"]["docno"] for e in listed})
    held = holders(numbers, candidates) if numbers else {}
    rows += listed_rows(listed, held)
    unmatched = [n for n in numbers if not held.get(n)]
    if unmatched:
        rows.append(_note("not_held", f"{len(unmatched)} of {len(numbers)} listed documents were not found among the documents you may read (matched by document number in the held document's title block); revision and sheets not compared for them"))
    if blocked:
        rows.append(_note("list_not_allowed", f"{blocked} of {len(named)} named required-submissions list documents are not in the documents you may read; not read"))
    if not named:
        rows.append(_note("no_list", "Transmittal kit: no required-submissions list named; required and extra items not checked"))
    elif allowed:
        items = required_items(allowed)
        if items:
            boundary = (
                f"({len(items)} required items read from {len(allowed)} named list "
                f"document(s); {len(listed)} documents listed on this transmittal only.)"
            )
            rows += required_rows(items, listed, boundary)
        else:
            rows.append(_note("list_no_items", "No table of required items was read from the named required-submissions list; required and extra items not checked"))
    return rows


def for_review(review_run_id: str, scope: frozenset[str]) -> None:
    """The review job's call, after the comparison. A failure never fails the review."""
    try:
        row = connect().execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?", (review_run_id,)
        ).fetchone()
        doc = row[0] if row else None
        if applies(doc):
            spec_kit._store(review_run_id, doc, rows_for(doc, scope))
    except Exception as exc:  # noqa: BLE001 - the kit is optional; the review stands
        log.warning("transmittal kit skipped: %s", type(exc).__name__)
