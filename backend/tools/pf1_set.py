"""PF1 (#881): build the unfamiliar-datasheet test set from a LOCAL spec.

The set proves (or disproves) that a review works beyond the sheets it was
developed on: invented datasheets of several equipment types and layouts,
each with planted defects, correct items and traps, and the answers a review
should give. THIS FILE HOLDS NO SET CONTENT. It turns a spec file a person
keeps on this machine into the files a review reads and a scorer scores:

  <out>/<id>.datasheet.pdf   the invented sheet (one of ten layouts)
  <out>/<id>.standard.pdf    the invented standard the sheet cites
  <out>/<id>.key.json        the answers, format `review-answer-key/1`
  <out>/index.json           document, equipment type, held out, files

THREE RULES THE BUILDER ENFORCES, because a wrong key proves nothing:

  1. THE KEY IS WRITTEN FROM THE ROWS THAT ARE DRAWN. A keyed row's value is
     read back from the finished page (a text layout) before the key is
     written; a value that is in the key and not on the page stops the build.
  2. EVERY KEYED CLAUSE EXISTS IN THE STANDARD, and the sheet cites the
     standard by number. An answer about a clause nobody can open is refused.
  3. THE SET NEVER LANDS IN A GIT REPOSITORY. Held-out answers on GitHub are
     not held out. The output folder is refused when it is inside one.

The spec (`pf1-spec/1`) is described in `eval/review/pf1.md`. Everything in a
spec must be invented: no value, tag or sentence from a real document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

SPEC_FORMAT = "pf1-spec/1"
KEY_FORMAT = "review-answer-key/1"
INDEX_FORMAT = "pf1-index/1"
ITEM_KINDS = ("defect", "met", "trap", "not_applicable")

A4 = (595, 842)
FONT = 9
LEFT = 40
TOP = 110
BOTTOM = 790


class SpecError(ValueError):
    """The spec cannot give a set whose answers can be trusted."""


# ------------------------------------------------------------------ the spec

def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def printed(row: dict) -> str:
    """A row's value as it is printed: the value, then its unit."""
    value, unit = _text(row.get("value")), _text(row.get("unit"))
    return f"{value} {unit}".strip()


def clause_numbers(standard: dict) -> set[str]:
    return {_text(s.get("clause")) for s in standard.get("sections") or [] if _text(s.get("clause"))}


def _under(clause: str, known: set[str]) -> bool:
    """A keyed clause is in the standard when it, or a clause above it, is a
    section: `4.2.1` is under `4.2`; `4.20` is not."""
    parts = clause.split(".")
    return any(".".join(parts[:n]) in known for n in range(len(parts), 0, -1))


def validate(spec: object) -> dict:
    """The spec, or a SpecError naming the first thing wrong with it."""
    if not isinstance(spec, dict) or spec.get("format") != SPEC_FORMAT:
        raise SpecError(f"the spec must be a JSON object with format {SPEC_FORMAT!r}")
    documents = spec.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SpecError("the spec has no documents")
    seen: set[str] = set()
    for doc in documents:
        doc_id = _text(doc.get("id")) if isinstance(doc, dict) else ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", doc_id) or doc_id in seen:
            raise SpecError(f"document id {doc_id!r}: lower-case letters, digits and dashes, and unique")
        seen.add(doc_id)
        if not _text(doc.get("equipment_type")):
            raise SpecError(f"{doc_id}: equipment_type is required")
        if not isinstance(doc.get("held_out"), bool):
            raise SpecError(f"{doc_id}: held_out must be true or false (never left to a default)")
        if doc.get("layout") not in LAYOUTS:
            raise SpecError(f"{doc_id}: layout must be one of {', '.join(LAYOUTS)}")
        sheet, standard = doc.get("sheet"), doc.get("standard")
        if not isinstance(sheet, dict) or not isinstance(standard, dict):
            raise SpecError(f"{doc_id}: a sheet and a standard are required")
        if not _text(standard.get("number")) or not standard.get("sections"):
            raise SpecError(f"{doc_id}: the standard needs a number and sections")
        pages = sheet.get("pages")
        if not isinstance(pages, list) or not pages or not all(p.get("rows") for p in pages):
            raise SpecError(f"{doc_id}: the sheet needs pages, each with rows")
        known = clause_numbers(standard)
        items = key_items(doc)
        ids = [it["id"] for it in items]
        if len(set(ids)) != len(ids) or not all(ids):
            raise SpecError(f"{doc_id}: every keyed item needs an id, unique in its document")
        for item in items:
            if item["kind"] not in ITEM_KINDS:
                raise SpecError(f"{doc_id} {item['id']}: kind must be one of {', '.join(ITEM_KINDS)}")
            own = item["standard"] == _text(standard.get("number"))
            if not item["clause"] or (own and not _under(item["clause"], known)):
                raise SpecError(f"{doc_id} {item['id']}: clause {item['clause']!r} is not in the standard")
        kinds = {it["kind"] for it in items}
        if "defect" not in kinds or not kinds & {"met", "trap"}:
            raise SpecError(f"{doc_id}: a document needs at least one planted defect and one correct item "
                            "(a set of defects only cannot show a false flag)")
    return spec


def _keys(row: dict) -> list[dict]:
    """A row's answers: none, one (`key`), or several (`key` as a list - the
    same printed value answers a clause of the invented standard AND a rule
    of a checklist the product already holds)."""
    key = row.get("key")
    return [key] if isinstance(key, dict) else [k for k in key or [] if isinstance(k, dict)]


def key_items(doc: dict) -> list[dict]:
    """The answers of one document, in the order they are drawn: one per
    keyed row (with its page), then the items no row carries (a value the
    sheet leaves out altogether, a clause that does not apply).

    An item is about the document's own invented standard unless it names
    another (`standard`): a rule of a checklist the product holds. Such a
    clause cannot be checked against the invented standard and is not."""
    number = _text(doc["standard"].get("number"))
    items: list[dict] = []

    def item(key: dict, *, field=None, page=None) -> dict:
        out = {"id": _text(key.get("id")), "kind": key.get("kind"),
               "standard": _text(key.get("standard")) or number, "clause": _text(key.get("clause"))}
        if _text(key.get("field") or field):
            out["field"] = _text(key.get("field") or field)
        if page is not None:
            out["submittal_page"] = page
        if _text(key.get("note")):
            out["note"] = _text(key.get("note"))
        return out

    for page_no, page in enumerate(doc["sheet"].get("pages") or [], start=1):
        for row in page.get("rows") or []:
            for key in _keys(row):
                items.append(item(key, field=row.get("field"), page=page_no))
    for key in doc.get("unprinted") or []:
        items.append(item(key))
    return items


# ---------------------------------------------------------------- the drawing

def _new_page(doc: pymupdf.Document, sheet: dict, number: int, total: int):
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_text((LEFT, 40), _text(sheet.get("title")) or "DATASHEET", fontsize=12, fontname="hebo")
    page.insert_text((LEFT, 58), f"Doc No.: {_text(sheet.get('document_number'))}", fontsize=FONT)
    page.insert_text((220, 58), f"Tag No.: {_text(sheet.get('tag'))}", fontsize=FONT)
    page.insert_text((400, 58), f"Rev: {_text(sheet.get('revision')) or '0'}", fontsize=FONT)
    page.insert_text((LEFT, 72), f"Project: {_text(sheet.get('project')) or 'Synthetic Plant 0001'}", fontsize=FONT)
    page.insert_text((400, 72), f"Sheet {number} of {total}", fontsize=FONT)
    return page


def _ruled(page, top: float, widths: list[int], rows: list[list], *, height=18, bold_first=False) -> float:
    y = top
    for n, cells in enumerate(rows):
        x = LEFT
        for width, cell in zip(widths, cells):
            page.draw_rect(pymupdf.Rect(x, y, x + width, y + height), color=(0, 0, 0), width=0.6)
            if _text(cell):
                font = "hebo" if bold_first and n == 0 else "helv"
                # A label that runs over its cell prints on top of the value
                # beside it: the sheet would be unreadable for a reason nobody
                # planted, and the review would be blamed for it.
                if pymupdf.get_text_length(_text(cell), fontname=font, fontsize=FONT) > width - 6:
                    raise SpecError(f"the text {_text(cell)!r} does not fit its {width}-point cell")
                page.insert_text((x + 4, y + height - 5), _text(cell), fontsize=FONT, fontname=font)
            x += width
        y += height
    return y


def _notes(page, y: float, lines: list[str]) -> None:
    for line in lines:
        page.insert_text((LEFT, y + 16), _text(line), fontsize=FONT)
        y += 14


def _draw_ruled_units(page, rows):
    return _ruled(page, TOP, [230, 150, 90], [["Description", "Value", "Unit"]]
                  + [[r["field"], _text(r.get("value")), _text(r.get("unit"))] for r in rows], bold_first=True)


def _draw_odd_headers(page, rows):
    return _ruled(page, TOP, [60, 200, 140, 80], [["Ref", "Parameter", "Data", "UoM"]]
                  + [[str(n), r["field"], _text(r.get("value")), _text(r.get("unit"))]
                     for n, r in enumerate(rows, start=1)], bold_first=True)


def _draw_required_offered(page, rows):
    return _ruled(page, TOP, [190, 110, 110, 70], [["Item", "Required", "Offered", "Unit"]]
                  + [[r["field"], _text(r.get("required")), _text(r.get("value")), _text(r.get("unit"))]
                     for r in rows], bold_first=True)


def _draw_numbered_lines(page, rows):
    return _ruled(page, TOP, [34, 236, 210], [[str(n), r["field"], printed(r)]
                                             for n, r in enumerate(rows, start=1)])


def _draw_two_column_form(page, rows):
    y = TOP
    for left, right in zip(rows[::2], rows[1::2] + [None] * (len(rows) % 2)):
        cells = [left["field"], printed(left)] + ([right["field"], printed(right)] if right else ["", ""])
        y = _ruled(page, y, [160, 105, 160, 105], [cells])
    return y


def _draw_label_value(page, rows):
    y = TOP
    for r in rows:
        page.insert_text((LEFT, y + 12), f"{r['field']} : {printed(r)}", fontsize=FONT)
        y += 17
    return y


def _draw_sentences(page, rows):
    y = TOP
    for r in rows:
        page.insert_text((LEFT, y + 12), f"The {r['field'][:1].lower()}{r['field'][1:]} is {printed(r)}.",
                         fontsize=FONT)
        y += 17
    return y


def _draw_merged_cells(page, rows):
    """A group heading spans the table; its rows sit beneath it."""
    y, group = TOP, object()
    for r in rows:
        if _text(r.get("group")) != group:
            group = _text(r.get("group"))
            if group:
                y = _ruled(page, y, [470], [[group]], bold_first=True)
        y = _ruled(page, y, [230, 240], [[r["field"], printed(r)]])
    return y


#: layout -> (how its rows are drawn, has the page a text layer, is it turned).
LAYOUTS = {
    "ruled_units": (_draw_ruled_units, True, False),
    "two_column_form": (_draw_two_column_form, True, False),
    "required_offered": (_draw_required_offered, True, False),
    "label_value": (_draw_label_value, True, False),
    "odd_headers": (_draw_odd_headers, True, False),
    "numbered_lines": (_draw_numbered_lines, True, False),
    "merged_cells": (_draw_merged_cells, True, False),
    "sentences": (_draw_sentences, True, False),
    "landscape": (_draw_ruled_units, True, True),
    "scanned": (_draw_ruled_units, False, False),
}


def datasheet_pdf(doc: dict) -> bytes:
    """The invented sheet. The standard it is made to is cited on page 1."""
    draw, text_layer, turned = LAYOUTS[doc["layout"]]
    sheet = doc["sheet"]
    pages = sheet["pages"]
    pdf = pymupdf.open()
    for number, spec_page in enumerate(pages, start=1):
        page = _new_page(pdf, sheet, number, len(pages))
        y = draw(page, spec_page["rows"])
        notes = list(spec_page.get("notes") or [])
        if number == 1:
            notes.insert(0, f"Applicable standard: {_text(doc['standard']['number'])}")
        _notes(page, y, notes)
        if turned:
            page.set_rotation(90)
    if not text_layer:                       # a scan: the same pages as pixels only
        scan = pymupdf.open()
        for page in pdf:
            png = page.get_pixmap(dpi=130, colorspace=pymupdf.csGRAY).tobytes("png")
            scan.new_page(width=A4[0], height=A4[1]).insert_image(pymupdf.Rect(0, 0, *A4), stream=png)
        pdf.close()
        pdf = scan
    return _bytes(pdf)


def standard_pdf(doc: dict) -> bytes:
    """The invented standard: numbered clauses as wrapped prose, a table
    where a section carries one, the number on every page."""
    standard = doc["standard"]
    number, title = _text(standard["number"]), _text(standard.get("title"))
    pdf = pymupdf.open()
    state = {"page": None, "y": BOTTOM}

    def page_for(height: float):
        if state["page"] is None or state["y"] + height > BOTTOM:
            state["page"] = pdf.new_page(width=A4[0], height=A4[1])
            state["page"].insert_text((LEFT, 40), f"{number}  {title}", fontsize=10, fontname="hebo")
            state["page"].insert_text((LEFT, 54), f"Revision {_text(standard.get('revision')) or '0'}"
                                                  "   Engineering Standard (invented for testing)", fontsize=8)
            state["y"] = 80
        return state["page"]

    for section in standard["sections"]:
        heading = f"{_text(section.get('clause'))}  {_text(section.get('title'))}".strip()
        body = _text(section.get("text"))
        lines = max(1, -(-len(body) // 95)) if body else 0
        table = section.get("table") or []
        page = page_for(22 + lines * 12 + len(table) * 18 + 12)
        if heading:
            page.insert_text((LEFT, state["y"] + 12), heading, fontsize=10, fontname="hebo")
            state["y"] += 20
        if body:
            box = pymupdf.Rect(LEFT, state["y"], A4[0] - LEFT, state["y"] + lines * 12 + 10)
            if page.insert_textbox(box, body, fontsize=FONT) < 0:
                raise SpecError(f"{doc['id']}: clause {section.get('clause')} is too long for its box")
            state["y"] = box.y1
        if table:
            widths = [int(470 / len(table[0]))] * len(table[0])
            state["y"] = _ruled(page, state["y"] + 4, widths, table, bold_first=True)
        state["y"] += 10
    return _bytes(pdf)


def _bytes(pdf: pymupdf.Document) -> bytes:
    """The same bytes on every run: no metadata, no new document id."""
    pdf.set_metadata({})
    data = pdf.tobytes(garbage=4, deflate=True, no_new_id=True)
    pdf.close()
    return data


# ------------------------------------------------------------------ the check

def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def unprinted_keyed_rows(doc: dict, pdf_bytes: bytes) -> list[str]:
    """RULE 1: the ids of keyed rows whose printed value is NOT on their page
    of the finished sheet. A scan has no text to read back and is checked on
    the page it was made from (see `build`)."""
    pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    missing = []
    try:
        for page_no, spec_page in enumerate(doc["sheet"]["pages"], start=1):
            on_page = _squash(pdf[page_no - 1].get_text()) if page_no <= len(pdf) else ""
            for row in spec_page["rows"]:
                if _keys(row) and (
                        _squash(row["field"]) not in on_page or _squash(printed(row)) not in on_page):
                    missing.extend(_text(key.get("id")) for key in _keys(row))
    finally:
        pdf.close()
    return missing


def cites_the_standard(doc: dict, pdf_bytes: bytes) -> bool:
    """RULE 2 (second half): the standard's number is printed on the sheet."""
    pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return _squash(doc["standard"]["number"]) in _squash(pdf[0].get_text())
    finally:
        pdf.close()


def inside_a_git_repository(path: Path) -> bool:
    """RULE 3: is `path` (or the nearest folder that exists above it) inside
    a git work tree?"""
    here = Path(path).resolve()
    return any((folder / ".git").exists() for folder in (here, *here.parents))


def answer_key(doc: dict) -> dict:
    """`complete_for_flags` is true unless the spec says the key does NOT
    list every defect on the sheet (a type whose checklist runs calculations
    the spec's author did not verify by hand): then an extra flag is "not
    judged by the key", never a false positive the review did not earn."""
    return {"format": KEY_FORMAT, "name": doc["id"], "source": "invented",
            "complete_for_flags": doc.get("complete_for_flags", True) is not False, "items": key_items(doc)}


def build(spec: dict, out_dir: str | Path) -> dict:
    """Write the set under `out_dir` and return its index. Nothing is written
    unless every document passes the three rules."""
    spec = validate(spec)
    out = Path(out_dir)
    if inside_a_git_repository(out):
        raise SpecError(f"{out} is inside a git repository: the set and its answers stay out of git")
    files: dict[str, bytes] = {}
    entries = []
    for doc in spec["documents"]:
        sheet = datasheet_pdf(doc)
        # a scan is checked on the text page it is a picture of
        readable = sheet if LAYOUTS[doc["layout"]][1] else datasheet_pdf({**doc, "layout": "ruled_units"})
        missing = unprinted_keyed_rows(doc, readable)
        if missing:
            raise SpecError(f"{doc['id']}: keyed values that are not on their page: {', '.join(missing)}")
        if not cites_the_standard(doc, readable):
            raise SpecError(f"{doc['id']}: the sheet does not print its standard's number")
        key = answer_key(doc)
        names = {"datasheet": f"{doc['id']}.datasheet.pdf", "standard": f"{doc['id']}.standard.pdf",
                 "key": f"{doc['id']}.key.json"}
        files[names["datasheet"]] = sheet
        files[names["standard"]] = standard_pdf(doc)
        files[names["key"]] = (json.dumps(key, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        counts = {kind: sum(1 for it in key["items"] if it["kind"] == kind) for kind in ITEM_KINDS}
        entries.append({"id": doc["id"], "equipment_type": _text(doc["equipment_type"]),
                        "held_out": doc["held_out"], "layout": doc["layout"],
                        "text_layer": LAYOUTS[doc["layout"]][1], "pages": len(doc["sheet"]["pages"]),
                        "standard_number": _text(doc["standard"]["number"]), "items": counts,
                        "complete_for_flags": key["complete_for_flags"], **names})
    index = {"format": INDEX_FORMAT, "source": "invented", "documents": entries}
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def summary(index: dict) -> dict:
    """Counts only - what may be posted: documents, types, held out, items by
    kind. Never an id of a held-out item, a value or a clause."""
    docs = index["documents"]
    return {"documents": len(docs),
            "equipment_types": len({d["equipment_type"] for d in docs}),
            "layouts": len({d["layout"] for d in docs}),
            "held_out": sum(1 for d in docs if d["held_out"]),
            "without_a_text_layer": sum(1 for d in docs if not d["text_layer"]),
            "items": {kind: sum(d["items"][kind] for d in docs) for kind in ITEM_KINDS}}
