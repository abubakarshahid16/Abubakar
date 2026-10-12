"""R21 / #785: where each side of a finding sits, and the box to draw on it.

The side-by-side view showed two gaps on the findings an engineer sees most -
the datasheet checklist rows (planner, live PSV run 12 Oct 05:12 UTC):

1. NO BOX ON THE SUBMITTAL PAGE. The value read ("23.5 barg") is shorter than
   `highlight.locate` will place safely, so the page came back unboxed. The
   fact itself often knows where it was read: the geometry reader stores the
   value's box, and every reader keeps the line it read. So, in order:
     the stored quote (as before) -> the value's stored box (this fact, or the
     geometry reading of the same field and value on the same page) -> the
     fact's source line -> the value itself when it occurs EXACTLY ONCE on
     the page -> the field's label (boxed as the label, and said so).
2. NO STANDARD PAGE AT ALL. A checklist row carries a clause id ("API 520-I
   3.16") but no standard document or page. The standard is found in the held
   library by `applicability.find_standard` (the one matching rule) and the
   clause's page from the standard's own stored requirements, or failing that
   from a chunk that starts the clause; the clause sentence is boxed when it
   can be placed.

EVERY BOX IS EITHER RIGHT OR ABSENT, and `box` names which kind it is so the
screen never calls a label box "the value". Nothing here writes; a run made
before this change is resolved the same way when it is opened.
"""
from __future__ import annotations

import json
import re

from . import highlight

#: What kind of box was drawn - shown to the engineer in words.
QUOTE = "quote"                 # the finding's own stored text
VALUE_POSITION = "value_position"   # the value's box as the reader stored it
SOURCE_LINE = "source_line"     # the line the value was read from
VALUE_ONCE = "value_once"       # the value, the only time it appears on the page
LABEL = "label"                 # the field's label (the value sits beside it)
CLAUSE_TEXT = "clause_text"     # the clause's stored requirement sentence
CLAUSE_HEADING = "clause_heading"   # the clause number at the start of its line

CHECKLIST_ORIGIN = "datasheet_check"

_CLAUSE = re.compile(r"^(?P<standard>.+?)\s+(?P<clause>\d+(?:\.\d+)*[A-Za-z]?)$")


def split_clause(cited: str | None) -> tuple[str, str] | None:
    """('API 520-I', '3.16') from 'API 520-I 3.16'; None when the text does
    not end in a clause number."""
    m = _CLAUSE.match(" ".join(str(cited or "").split()))
    return (m["standard"], m["clause"]) if m else None


def _box(value) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            x0, y0, x1, y1 = (float(v) for v in value[:4])
        except (TypeError, ValueError):
            return None
        if x1 > x0 and y1 > y0:
            return (x0, y0, x1, y1)
    return None


def _value_box(fact: dict) -> tuple[float, float, float, float] | None:
    try:
        stored = json.loads(fact.get("bbox") or "null")
    except (TypeError, ValueError):
        return None
    if isinstance(stored, dict):
        return _box(stored.get("value_bbox"))
    return _box(stored)


def _once(pdf_path: str, page_no: int, text: str) -> list[tuple[float, float, float, float]]:
    """The text's box when it occurs exactly once on the page, else none: a
    short value found twice could be either, and a guessed box is worse than
    no box."""
    import pymupdf

    text = " ".join(str(text or "").split())
    if len(text) < 3:
        return []
    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_no <= doc.page_count:
            return []
        found = doc.load_page(page_no - 1).search_for(text, quads=False)
    return [(r.x0, r.y0, r.x1, r.y1) for r in found] if len(found) == 1 else []


def _facts_for(finding: dict) -> list[dict]:
    """The finding's own fact, then the other readings of the same field and
    value on the same page (the geometry reader stores a position the text
    reader does not)."""
    from .db import connect

    if not finding.get("fact_id"):
        return []
    conn = connect()
    own = conn.execute("SELECT * FROM submittal_facts WHERE id = ?",
                       (finding["fact_id"],)).fetchone()
    if own is None:
        return []
    own = dict(own)
    others = [dict(r) for r in conn.execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND page = ?"
        " AND field_label = ? AND raw_value = ? AND id != ?",
        (own["submittal_document_id"], own["page"], own.get("field_label"),
         own.get("raw_value"), own["id"]))]
    return [own, *others]


def submittal_box(finding: dict, pdf_path: str, page_no: int) -> tuple[list, str | None]:
    """(rectangles, kind) for the submittal side; ([], None) when nothing can
    be placed safely."""
    rects, _ = highlight.locate(pdf_path, page_no, finding.get("contractor_evidence_text") or "")
    if rects:
        return rects, QUOTE
    facts = [f for f in _facts_for(finding) if f.get("page") in (None, page_no)]
    for fact in facts:
        box = _value_box(fact)
        if box:
            return [box], VALUE_POSITION
    for fact in facts:
        rects, _ = highlight.locate(pdf_path, page_no, fact.get("source_text") or "")
        if rects:
            return rects, SOURCE_LINE
    rects = _once(pdf_path, page_no, finding.get("contractor_evidence_text") or "")
    if rects:
        return rects, VALUE_ONCE
    label = finding.get("contractor_section") or (facts[0].get("field_label") if facts else "")
    rects = _once(pdf_path, page_no, label or "")
    if rects:
        return rects, LABEL
    return [], None


def checklist_standard(finding: dict, allowed_document_ids: frozenset[str]) -> dict | None:
    """For a checklist row: {document_id, page, text, how} of the clause it
    cites, in a held standard the caller may read; None when the standard is
    not held, not readable, or the clause is not found in it."""
    from . import standards
    from .applicability import find_standard
    from .db import connect

    if finding.get("origin") != CHECKLIST_ORIGIN:
        return None
    parts = split_clause(finding.get("standard_clause"))
    if parts is None:
        return None
    name, clause = parts
    entry = find_standard(standards.list_standards(allowed_document_ids=allowed_document_ids),
                          name)
    if entry is None or entry["id"] not in allowed_document_ids:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT page, source_text, requirement_text FROM standard_requirements"
        " WHERE standard_document_id = ? AND clause = ? AND page IS NOT NULL"
        " ORDER BY page LIMIT 1", (entry["id"], clause)).fetchone()
    if row is not None:
        return {"document_id": entry["id"], "page": int(row["page"]),
                "text": row["source_text"] or row["requirement_text"], "how": CLAUSE_TEXT}
    heading = re.compile(rf"(?:^|\n)\s*({re.escape(clause)}\s+\S[^\n]*)")
    for chunk in conn.execute(
            "SELECT page_start, text FROM chunks WHERE document_id = ? AND page_start IS NOT NULL"
            " ORDER BY page_start, ordinal", (entry["id"],)):
        m = heading.search(chunk["text"] or "")
        if m:
            return {"document_id": entry["id"], "page": int(chunk["page_start"]),
                    "text": m[1].strip(), "how": CLAUSE_HEADING}
    return None


def standard_box(text: str | None, pdf_path: str, page_no: int, how: str) -> tuple[list, str | None]:
    rects, _ = highlight.locate(pdf_path, page_no, text or "")
    return (rects, how) if rects else ([], None)
