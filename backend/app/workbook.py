"""Read an xlsx into sheets for a read-only preview. Standard library only.

WHY THIS IS SERVER-SIDE AND NOT A FRONTEND LIBRARY

The obvious move is SheetJS in the browser. Against it:

  * the npm `xlsx` package is no longer published there by its authors, so
    `npm install xlsx` fetches a stale 0.18.x with published prototype
    pollution advisories - a poor thing to add to a product whose entire
    premise is that documents are safe on this machine;
  * it is a third-party parser running over a file an outside contractor
    supplied, inside the reader's browser;
  * `zipfile` and `xml.etree` are already here, already used by
    `upload.validate_xlsx`, and cost nothing.

THE ORIGINAL IS NEVER MODIFIED. This reads; it does not convert. The stored
bytes remain exactly what was uploaded, and "download original" serves those
same bytes - master-plan section 27.

EVERYTHING IS BOUNDED. A workbook is an untrusted zip full of untrusted XML, so
every loop here has a ceiling and every ceiling is stated. `validate_xlsx`
already refused the file if its DECLARED expansion was implausible; these
bounds are the second half, applied while actually reading.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

#: OOXML namespaces. Fixed strings, so a workbook cannot redirect the parse by
#: declaring something else.
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

#: Ceilings for the PREVIEW. This is a preview, not an export: a reader needs
#: to see what the form asks for, not every cell of a 100,000-row sheet. Each
#: is reported as truncation rather than silently applied - a preview that
#: quietly stops at row 500 is a preview that lies about what the file holds.
MAX_SHEETS = 25
MAX_ROWS_PER_SHEET = 500
MAX_COLS_PER_ROW = 60
MAX_CELL_CHARS = 500
#: A ceiling on decompressed bytes read per part, so a part that lied about its
#: declared size cannot be streamed indefinitely here.
MAX_PART_BYTES = 32 * 1024 * 1024


class WorkbookError(Exception):
    """The file could not be read as a workbook."""


def _read_part(book: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        with book.open(name) as part:
            data = part.read(MAX_PART_BYTES + 1)
    except KeyError:
        return None
    if len(data) > MAX_PART_BYTES:
        raise WorkbookError(f"{name} is larger than this preview will read")
    return data


def _parse(data: bytes) -> ET.Element:
    """Parse one part.

    `xml.etree` does not expand external entities, so an XXE pointing at a
    local file does not resolve. An undefined entity raises rather than
    silently expanding, which is the billion-laughs case.
    """
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise WorkbookError(f"malformed XML: {exc}") from exc


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    data = _read_part(book, "xl/sharedStrings.xml")
    if data is None:
        return []
    root = _parse(data)
    out: list[str] = []
    for si in root.iter(f"{_MAIN}si"):
        # A string can be split across runs (<r><t>) when parts of it are
        # styled differently; joining every <t> under the <si> is what puts
        # "Design Pressure" back together instead of yielding "Design".
        text = "".join(t.text or "" for t in si.iter(f"{_MAIN}t"))
        out.append(text[:MAX_CELL_CHARS])
    return out


def _column_index(ref: str) -> int:
    """`B7` -> 1. Letters only; a missing or odd ref yields 0."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return max(n - 1, 0)


def _sheet_targets(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    """`[(sheet name, part path)]`, in the workbook's own tab order.

    Resolved through the relationship file rather than by assuming
    `sheet1.xml`, `sheet2.xml`: the part names are arbitrary, and a workbook
    saved by anything other than Excel frequently does not follow that
    pattern. Tab order comes from `workbook.xml`, so the preview's tabs are in
    the order the author put them.
    """
    book_xml = _read_part(book, "xl/workbook.xml")
    if book_xml is None:
        raise WorkbookError("no xl/workbook.xml")
    rels_xml = _read_part(book, "xl/_rels/workbook.xml.rels")
    rels: dict[str, str] = {}
    if rels_xml is not None:
        for rel in _parse(rels_xml).iter(f"{_PKG_REL}Relationship"):
            rid = rel.get("Id")
            target = rel.get("Target")
            if rid and target:
                rels[rid] = target.lstrip("/")

    out: list[tuple[str, str]] = []
    for sheet in _parse(book_xml).iter(f"{_MAIN}sheet"):
        name = sheet.get("name") or "Sheet"
        rid = sheet.get(f"{_REL}id")
        target = rels.get(rid or "")
        if target is None:
            continue
        path = target if target.startswith("xl/") else f"xl/{target}"
        out.append((name, path))
        if len(out) >= MAX_SHEETS:
            break
    return out


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "s":
        v = cell.find(f"{_MAIN}v")
        try:
            return shared[int(v.text or "0")] if v is not None else ""
        except (ValueError, IndexError):
            return ""
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{_MAIN}t"))[:MAX_CELL_CHARS]
    # A formula cell carries its LAST COMPUTED VALUE in <v>. That is what the
    # reader saw in Excel, so it is what the preview shows; the formula itself
    # is not re-evaluated here and never will be.
    v = cell.find(f"{_MAIN}v")
    if v is not None and v.text is not None:
        return v.text[:MAX_CELL_CHARS]
    t = cell.find(f"{_MAIN}t")
    return (t.text or "")[:MAX_CELL_CHARS] if t is not None else ""


def read_sheets(path: Path) -> dict:
    """`{"sheets": [{"name", "rows", "truncated"}], "truncated": bool}`.

    POPULATED CELLS ONLY. A CRS template is mostly empty, and a preview of its
    full addressable grid is thousands of blanks around the few cells that say
    anything. An empty row is dropped; an empty cell is an empty string, which
    the UI renders as nothing rather than as 0.
    """
    try:
        with zipfile.ZipFile(path) as book:
            shared = _shared_strings(book)
            targets = _sheet_targets(book)
            sheets = []
            truncated_any = False
            for name, part in targets:
                data = _read_part(book, part)
                if data is None:
                    continue
                root = _parse(data)
                rows: list[list[str]] = []
                truncated = False
                for row in root.iter(f"{_MAIN}row"):
                    if len(rows) >= MAX_ROWS_PER_SHEET:
                        truncated = True
                        break
                    cells: list[str] = []
                    for cell in row.iter(f"{_MAIN}c"):
                        index = _column_index(cell.get("r") or "")
                        if index >= MAX_COLS_PER_ROW:
                            truncated = True
                            continue
                        # Sparse rows: a row with A1 and D1 has no B or C
                        # elements at all, so the gap is filled to keep the
                        # columns aligned with what Excel shows.
                        while len(cells) < index:
                            cells.append("")
                        cells.append(_cell_text(cell, shared))
                    if any(c != "" for c in cells):
                        rows.append(cells)
                truncated_any = truncated_any or truncated
                sheets.append({"name": name, "rows": rows, "truncated": truncated})
            return {"sheets": sheets, "truncated": truncated_any}
    except zipfile.BadZipFile as exc:
        raise WorkbookError(f"not a readable workbook: {exc}") from exc
