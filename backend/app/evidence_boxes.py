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
3. NO VALUE FOUND, NOTHING TO SHOW (#785 point 3, planner 12 Oct). A row the
   checklist could not find a value for ("PSV-11") cites no page. The engineer
   is shown WHERE TO LOOK: the field's label (its own name, or a spelling the
   rules list for it) when it is printed EXACTLY ONCE in the whole datasheet,
   boxed as "where to look"; printed more than once, no box and the pages in
   words; not printed, words naming the field and the pages to check (a page
   with no text layer is named: the label could be there, read by eye).

4. A SCANNED PAGE (#508). A page with no text layer has nothing for the
   searches above to find. Its lines are recognised by the project's own OCR
   (`ocr.page_lines`: the same engine, models and DPI, in a child process)
   and the recognised line holding the cited text is boxed - only when that
   text is in EXACTLY ONE line. Otherwise the page is shown unboxed with the
   reason in words: not found among the recognised lines, or recognition
   could not run here.

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
WHERE_TO_LOOK = "where_to_look"  # no value found: the field's label, the one place it is printed
OCR_LINE = "ocr_line"           # #508: a scanned page - the recognised line holding the cited text

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


def _spellings(field: str) -> list[str]:
    """The field's own name, then the plain spellings the checklist rules list
    for it (`printed_as`, `field_synonyms.json`) - text, never a pattern, so a
    box is only ever drawn on words the page prints."""
    from . import datasheet_checks

    role = "_".join(field.lower().split())
    rules = datasheet_checks.load_rules()
    out = [" ".join(field.split())]
    out += list(rules["roles"].get(role, {}).get("printed_as", []))
    out += datasheet_checks._synonyms().get(role.replace("_", " ")) or []
    seen, kept = set(), []
    for s in out:
        key = " ".join(str(s).lower().split())
        if len(key) >= 3 and key not in seen:
            seen.add(key)
            kept.append(" ".join(str(s).split()))
    return kept


def _inside(a, b) -> bool:
    return a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1


def where_to_look(field: str | None, pdf_path: str) -> dict:
    """For a row with no value and no page: {page, rects, reason}. A page and
    one box only when the field's label is printed exactly once in the whole
    datasheet; otherwise no page, and `reason` says in words where to look.
    Reads the PDF only; writes nothing."""
    import pymupdf

    field = " ".join(str(field or "").split())
    if not field:
        return {"page": None, "rects": [],
                "reason": "no value was found, and the finding does not name the field"}
    hits: list[tuple[int, tuple]] = []
    blank: list[int] = []
    with pymupdf.open(pdf_path) as doc:
        count = doc.page_count
        for index in range(count):
            page = doc.load_page(index)
            if not page.get_text().strip():
                blank.append(index + 1)
                continue
            for spelling in _spellings(field):
                for r in page.search_for(spelling, quads=False):
                    hits.append((index + 1, (r.x0, r.y0, r.x1, r.y1)))
    # A shorter spelling found inside a longer one is the same place, not two.
    places = [h for h in hits if not any(o is not h and o[0] == h[0] and _inside(h[1], o[1])
                                         and not _inside(o[1], h[1]) for o in hits)]
    unique: list[tuple[int, tuple]] = []
    for h in places:
        if not any(u[0] == h[0] and _inside(h[1], u[1]) for u in unique):
            unique.append(h)
    if len(unique) == 1 and not blank:
        return {"page": unique[0][0], "rects": [unique[0][1]], "reason": None}
    no_text = (f"; page{'s' if len(blank) > 1 else ''} {_pages(blank)} "
               f"{'have' if len(blank) > 1 else 'has'} no text layer, so check "
               f"{'them' if len(blank) > 1 else 'it'} by eye") if blank else ""
    if unique:
        pages = sorted({u[0] for u in unique})
        return {"page": None, "rects": [], "reason":
                f"no value was found for {field}; its label is printed {len(unique)} times "
                f"(page{'s' if len(pages) > 1 else ''} {_pages(pages)}), so no box is drawn - "
                f"check the {field} entry on {'those pages' if len(pages) > 1 else 'that page'}"
                + no_text}
    return {"page": None, "rects": [], "reason":
            f"no value was found for {field}, and its label is not printed on the datasheet "
            f"(pages {_pages(list(range(1, count + 1)))} searched) - check the section where "
            f"{field} would be given, or ask the contractor for it" + no_text}


def _pages(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers) if numbers else "none"


def has_text_layer(pdf_path: str, page_no: int) -> bool:
    """Does the page carry any text a search can find? A page out of range
    counts as having one: nothing here is the place to report it."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_no <= doc.page_count:
            return True
        return bool((doc.load_page(page_no - 1).get_text("text") or "").strip())


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def scanned_box(texts: list[str], pdf_path: str, page_no: int,
                sha256: str) -> tuple[list, str | None, str | None]:
    """#508: (rectangles, kind, reason) on a scanned page. Each text is tried
    whole and then as the same shorter pieces `highlight.locate` tries; a
    piece is boxed only when exactly one recognised line holds it."""
    from . import ocr

    try:
        lines = ocr.page_lines(pdf_path, sha256, page_no)
    except ocr.PageLinesUnavailable as exc:
        return [], None, (f"page {page_no} is a scanned image with no text layer and could not "
                          f"be read here ({exc}), so no box is drawn - read the page itself")
    recognised = [(_norm(t), box) for t, box in lines if _norm(t)]
    for text in texts:
        whole = _norm(text)
        pieces = ([whole] if len(whole) >= 3 else []) + [
            _norm(p) for p in highlight._candidates(text or "")]
        for piece in dict.fromkeys(pieces):
            hits = [box for line, box in recognised if piece and piece in line]
            if len(hits) == 1 and _box(hits[0]):
                return [_box(hits[0])], OCR_LINE, None
    return [], None, (f"page {page_no} is a scanned image with no text layer; the cited text "
                      "was not found in exactly one of the lines recognised on it, so no box "
                      "is drawn - read the page itself")


def submittal_texts(finding: dict) -> list[str]:
    """What a scanned submittal page is searched for: the finding's own text,
    then the lines its facts were read from."""
    texts = [finding.get("contractor_evidence_text") or ""]
    texts += [f.get("source_text") or "" for f in _facts_for(finding)]
    return [t for t in dict.fromkeys(texts) if t.strip()]
