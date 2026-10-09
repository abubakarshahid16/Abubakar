"""Claim units for written documents (W5b-05, #529).

A procedure, a method statement or a submittal letter is not a datasheet: the
things a reviewer can check in it are its obligations (every "shall" and "must"
sentence), its table rows, and the standards it points to. This module breaks a
document into exactly those units, one each, every one with the page it is on,
so a later step (#530: a verdict per unit) has something to attach a verdict
and a citation to.

A UNIT IS A CITATION BEFORE IT IS ANYTHING ELSE. It is read page by page from
the stored page text, so its page is the page it was read from, not the first
page of a chunk that happens to span two (#660). The text is the sentence as the
page printed it, running header and footer removed first (a footer inside a
sentence is not part of the sentence).

THREE KINDS, NOTHING ELSE:
  * `obligation`  - a sentence with an obligation word (shall, must, is to be,
    ...), split the way `standards.extract_requirements` splits it, so the
    two readers cannot disagree about what one obligation is;
  * `table_row`   - one unit per data row of a ruled table the parser reads
    (`tables.parse_page_tables`), the row's label and every cell, not one per
    number;
  * `reference`   - one unit per standard named on a page, in the shared
    matcher's own grammar (`standard_ids.find_citations`).

NAMED STATES, NEVER A SILENT PASS. A page with no text is counted
(`pages_unread`); a document with no readable page is `no_text`; a Word file's
tables are not rows here (the ruling geometry a PDF parser needs does not exist
in them) and that is stated in `table_rows_unavailable`. A document that yields
no unit at all is not "clean": it is `no_units`.

No model, no network, no database write.
"""
from __future__ import annotations

import hashlib

from . import claims, standard_ids, standards, tables as tables_mod
from .db import connect

KIND_OBLIGATION = "obligation"
KIND_TABLE_ROW = "table_row"
KIND_REFERENCE = "reference"
KINDS = (KIND_OBLIGATION, KIND_TABLE_ROW, KIND_REFERENCE)


def _unit(document_id: str, kind: str, page: int, ordinal: int, text: str, **extra) -> dict:
    ident = hashlib.sha1(f"{document_id}|{kind}|{page}|{ordinal}|{text}".encode("utf-8")).hexdigest()[:16]
    return {"id": ident, "kind": kind, "page": page, "text": text,
            "citation": {"document_id": document_id, "page": page}, **extra}


def obligations_on_page(document_id: str, page: int, text: str) -> list[dict]:
    """Every obligation sentence on one page, in reading order."""
    out: list[dict] = []
    for joined in claims.split_sentences(standards.strip_page_furniture(text)):
        for sentence in standards._requirement_parts(joined):
            if not standards._MANDATORY.search(sentence):
                continue
            if len(sentence.split()) < standards.MIN_REQUIREMENT_WORDS:
                continue      # a heading or a cell that happens to contain "shall"
            out.append(_unit(document_id, KIND_OBLIGATION, page, len(out), sentence))
    return out


def table_rows_on_page(document_id: str, page: int, stored_path: str) -> list[dict]:
    """One unit per data row of every ruled table on the page."""
    out: list[dict] = []
    for table in tables_mod.parse_page_tables(stored_path, page):
        header, data = tables_mod._compose_header(table)
        for r, row in enumerate(data, start=1):
            cells = [(c or "").strip() for c in row]
            if not any(cells):
                continue
            label = cells[0]
            text = " | ".join(f"{header[i] if i < len(header) and header[i] else 'col ' + str(i + 1)}: {c}"
                              for i, c in enumerate(cells) if c)
            out.append(_unit(document_id, KIND_TABLE_ROW, page, len(out), text,
                             row=r, label=label, cells=cells, columns=list(header)))
    return out


def references_on_page(document_id: str, page: int, text: str) -> list[dict]:
    """One unit per standard named on the page (a standard named twice on a
    page is one unit; the same standard on another page is another unit)."""
    out: list[dict] = []
    for printed in standard_ids.cited_standards(text):
        out.append(_unit(document_id, KIND_REFERENCE, page, len(out), printed))
    return out


def units_for_document(document_id: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """Every claim unit of one document, or a named state saying why none."""
    if document_id not in allowed_document_ids:
        return {"document_id": document_id, "state": "not_readable", "units": [],
                "counts": {k: 0 for k in KINDS}, "pages_read": 0, "pages_unread": 0,
                "table_rows_unavailable": False}
    conn = connect()
    doc = conn.execute("SELECT stored_path, pagination FROM documents WHERE id = ?", (document_id,)).fetchone()
    pages = conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no", (document_id,)).fetchall()
    stored = doc["stored_path"] if doc is not None else ""
    # A Word file ("flow" pagination, #668) has no ruling geometry for the row parser.
    office = bool(doc is not None and doc["pagination"] == "flow")
    units: list[dict] = []
    read = unread = 0
    for page in pages:
        text = page["text"] or ""
        if not text.strip():
            unread += 1
            continue
        read += 1
        units += obligations_on_page(document_id, page["page_no"], text)
        if stored and not office:
            units += table_rows_on_page(document_id, page["page_no"], stored)
        units += references_on_page(document_id, page["page_no"], text)
    counts = {k: sum(1 for u in units if u["kind"] == k) for k in KINDS}
    if read == 0:
        state = "no_text"
    elif not units:
        state = "no_units"
    else:
        state = "ok"
    return {"document_id": document_id, "state": state, "units": units, "counts": counts,
            "pages_read": read, "pages_unread": unread, "table_rows_unavailable": office}
