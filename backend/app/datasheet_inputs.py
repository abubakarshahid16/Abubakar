"""Datasheet INPUTS other than a PDF text layer: Excel, Word, scanned pages.

WHY THIS MODULE EXISTS. The datasheet reader (`datasheets._extract_facts`)
opens every stored file with PyMuPDF. A workbook was stored but never read
(`upload.py`: `stored_not_indexed`), a Word file was refused at upload, and a
scanned page was read only through a "LABEL: VALUE" line in its OCR text. This
module turns each of those into PAGE TEXT - the same thing a PDF page gives -
plus the ROWS that text was rendered from, so:

  * the RULES reader gets label/value pairs (`pairs_from_rows`) that feed the
    unchanged fact pipeline, and every pair's label and value cells appear
    VERBATIM on one line of the page text, so a value stays provable against
    the text it was read from;
  * an AI reader gets the same page text, one string per page, with its source
    and (for OCR) its confidence, never a second, different rendering.

BEHIND `settings.datasheet_office_input` (env DATASHEET_OFFICE_INPUT), OFF by
default. With it off nothing in this module is reached from production code:
the seams in `upload.py`, `extract.py`, `tables.py` and `datasheets.py` check
the flag first, so merging this changes no behaviour until it is measured.

HOSTILE FILES. An upload is untrusted. Every limit below is enforced BEFORE the
work it bounds: a workbook's or document's declared unpacked size is checked
from the zip's central directory before anything is decompressed (the same
rule `upload.validate_xlsx` applies), a Word document's XML is refused if it
carries a DOCTYPE (no entity can be declared, so neither an external entity
nor an entity-expansion bomb can exist), and a sheet is read row by row with
a ceiling on rows, columns and cells. A limit that cuts content is REPORTED
(`Reading.notes`), never silent - a truncated sheet must not look complete.

NO FORMULA IS EVALUATED. Workbooks are opened `data_only=True, read_only=True`:
a formula cell yields the value Excel last cached for it, or nothing when no
cached value exists. The formula text itself never reaches the page text.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

SOURCE_PDF_TEXT = "pdf_text"
SOURCE_OCR = "ocr"
SOURCE_XLSX = "xlsx"
SOURCE_DOCX = "docx"

KIND_XLSX = "xlsx"
KIND_DOCX = "docx"

#: How a rendered row joins its cells. A row `Design pressure | 15 | barg`
#: reads naturally to a person and to a model, and splits back unambiguously.
CELL_SEPARATOR = " | "

# ------------------------------------------------------------------ limits
#: Per sheet: rows read, columns read per row. Content beyond is reported.
MAX_SHEET_ROWS = 5_000
MAX_SHEET_COLS = 100
#: Across the whole workbook: cells rendered. A datasheet is a few hundred.
MAX_TOTAL_CELLS = 200_000
#: Sheets read (visible ones); a workbook with more is refused, not cut.
MAX_SHEETS = 50
#: One cell's rendered text. A longer cell is cut and reported.
MAX_CELL_CHARS = 2_000
#: The unpacked size of ALL zip entries, declared, checked before opening.
#: The same ceiling the upload applies to a workbook.
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
#: Entries in the zip. Many tiny entries cost nothing in size and a lot in
#: syscalls.
MAX_ZIP_ENTRIES = 5_000
#: `word/document.xml` alone, declared AND read. It is parsed in memory.
MAX_DOCX_XML_BYTES = 32 * 1024 * 1024
#: Paragraphs + table rows in a Word document.
MAX_DOCX_BLOCKS = 50_000

#: The part only a real workbook has / only a real Word document has.
XLSX_REQUIRED_ENTRY = "xl/workbook.xml"
DOCX_REQUIRED_ENTRY = "word/document.xml"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class InputError(ValueError):
    """A file this module refuses to read. `code` is a stable slug."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PageText:
    """One page's text, where it came from and, for OCR, how sure.

    `rows` are the cells `text` was rendered from, one tuple per line of a
    table-shaped source (xlsx, docx; empty for a PDF text layer). Every row
    appears in `text` as `CELL_SEPARATOR.join(row)`, on its own line.
    """

    page_no: int
    text: str
    source: str
    confidence: float | None = None
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass
class Reading:
    pages: list[PageText]
    #: What was deliberately NOT read, in counts - never document text, so a
    #: note can be logged. "hidden sheet 2 skipped", "sheet 1 cut at 5000 rows".
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ kind


def office_kind(path: str | os.PathLike) -> str | None:
    """`xlsx`, `docx` or None, from the file's BYTES, never its name."""
    try:
        with open(path, "rb") as fh:
            if fh.read(len(_ZIP_MAGIC)) != _ZIP_MAGIC:
                return None
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if XLSX_REQUIRED_ENTRY in names:
        return KIND_XLSX
    if DOCX_REQUIRED_ENTRY in names:
        return KIND_DOCX
    return None


def check_zip_bounds(path: str | os.PathLike) -> None:
    """Refuse a zip whose declared unpacked size or entry count is too large.

    Reads the central directory only; nothing is decompressed. CPython's zip
    reader stops each entry at its declared `file_size`, so the declared sum
    bounds what any later read can expand to.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise InputError("not_office", "the file is not a readable zip") from exc
    if len(entries) > MAX_ZIP_ENTRIES:
        raise InputError("too_many_entries",
                         f"{len(entries)} zip entries, limit {MAX_ZIP_ENTRIES}")
    declared = sum(e.file_size for e in entries)
    if declared > MAX_UNCOMPRESSED_BYTES:
        raise InputError("too_large_unpacked",
                         f"declared {declared} bytes unpacked, limit {MAX_UNCOMPRESSED_BYTES}")
    names = {e.filename.lower() for e in entries}
    if any(n.startswith(("xl/vbaproject", "word/vbaproject")) for n in names):
        raise InputError("macro", "the file carries a macro project")


# ------------------------------------------------------------------ cells


def _cell_text(value) -> str:
    """One cell as text. Never a formula: `data_only=True` gives the cached
    value or None, and None is an empty cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return ""
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.12g}"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return " ".join(str(value).split())


def _clip(text: str, notes: list[str], where: str) -> str:
    if len(text) > MAX_CELL_CHARS:
        notes.append(f"{where}: a cell cut at {MAX_CELL_CHARS} characters")
        return text[:MAX_CELL_CHARS]
    return text


def _render(rows: list[tuple[str, ...]], heading: str | None = None) -> str:
    lines = [heading] if heading else []
    lines.extend(CELL_SEPARATOR.join(row) for row in rows)
    return "\n".join(lines)


# ------------------------------------------------------------------ xlsx


def _merged_ranges(zf: zipfile.ZipFile, sheet_xml: str) -> list[tuple[int, int, int, int]]:
    """(min_row, min_col, max_row, max_col) of every merged range of a sheet.

    Read from the sheet XML because openpyxl's read-only worksheet does not
    expose merged cells. Streamed with iterparse; only `mergeCell` elements
    are kept. The zip's bounds were checked before this is reached.
    """
    from openpyxl.utils.cell import range_boundaries

    out: list[tuple[int, int, int, int]] = []
    try:
        with zf.open(sheet_xml) as fh:
            for _event, elem in ET.iterparse(fh, events=("end",)):
                if elem.tag.endswith("}mergeCell"):
                    ref = elem.get("ref") or ""
                    try:
                        min_col, min_row, max_col, max_row = range_boundaries(ref)
                    except (TypeError, ValueError):
                        continue
                    out.append((min_row, min_col, max_row, max_col))
                    if len(out) > MAX_SHEET_ROWS:
                        break
                elem.clear()
    except (KeyError, ET.ParseError):
        return []
    return out


def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    """Sheet title -> its XML part, from workbook.xml and its relationships."""
    try:
        wb = _parse_bounded(zf, "xl/workbook.xml")
        rels = _parse_bounded(zf, "xl/_rels/workbook.xml.rels")
    except (KeyError, InputError, ET.ParseError):
        return {}
    targets = {r.get("Id"): r.get("Target") or "" for r in rels}
    out: dict[str, str] = {}
    for sheet in wb.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        rid = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), None)
        target = targets.get(rid, "")
        if not target:
            continue
        target = target.lstrip("/")
        out[sheet.get("name") or ""] = target if target.startswith("xl/") else f"xl/{target}"
    return out


def read_xlsx(path: str | os.PathLike) -> Reading:
    """One page per VISIBLE sheet, one line per non-empty row.

    MERGED CELLS: the value lives in the range's top-left cell only. A range
    spanning several ROWS repeats that value on each of its rows (so a label
    merged down beside three values labels all three); within a row it is
    written once. HIDDEN (and very hidden) sheets are skipped and noted.
    """
    import openpyxl

    check_zip_bounds(path)
    notes: list[str] = []
    pages: list[PageText] = []
    with zipfile.ZipFile(path) as zf:
        # openpyxl parses these parts itself; none may declare an entity.
        refuse_doctype(zf)
        sheet_xml = _sheet_paths(zf)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True,
                                    keep_links=False)
        try:
            if len(wb.worksheets) > MAX_SHEETS:
                raise InputError("too_many_sheets",
                                 f"{len(wb.worksheets)} sheets, limit {MAX_SHEETS}")
            cells_total = 0
            for index, ws in enumerate(wb.worksheets, start=1):
                if getattr(ws, "sheet_state", "visible") != "visible":
                    notes.append(f"hidden sheet {index} skipped")
                    continue
                merged = _merged_ranges(zf, sheet_xml[ws.title]) if ws.title in sheet_xml else []
                # (row, col) -> top-left value, for cells BELOW a range's first
                # row in its first column; every other covered cell stays empty.
                # Bounded like the cells: a hostile file could declare thousands
                # of sheet-long merges, and each covered row is an entry here.
                carried: dict[tuple[int, int], tuple[int, int]] = {}
                for r0, c0, r1, _c1 in merged:
                    for r in range(r0 + 1, min(r1, MAX_SHEET_ROWS) + 1):
                        carried[(r, c0)] = (r0, c0)
                    if len(carried) > MAX_TOTAL_CELLS:
                        raise InputError("too_many_cells",
                                         f"merged ranges cover more than {MAX_TOTAL_CELLS} cells")
                corners = {(r0, c0) for r0, c0, *_ in merged}
                top_left: dict[tuple[int, int], str] = {}
                rows: list[tuple[str, ...]] = []
                row_no = 0
                cut_rows = cut_cols = False
                for row_no, values in enumerate(ws.iter_rows(values_only=True), start=1):
                    if row_no > MAX_SHEET_ROWS:
                        cut_rows = True
                        break
                    if len(values) > MAX_SHEET_COLS:
                        cut_cols = True
                        values = values[:MAX_SHEET_COLS]
                    cells: list[str] = []
                    for col_no, value in enumerate(values, start=1):
                        text = _clip(_cell_text(value), notes, f"sheet {index}")
                        if (row_no, col_no) in corners:
                            top_left[(row_no, col_no)] = text
                        source = carried.get((row_no, col_no))
                        if not text and source is not None:
                            text = top_left.get(source, "")
                        if text:
                            cells.append(text)
                    cells_total += len(cells)
                    if cells_total > MAX_TOTAL_CELLS:
                        raise InputError("too_many_cells",
                                         f"more than {MAX_TOTAL_CELLS} populated cells")
                    if cells:
                        rows.append(tuple(cells))
                if cut_rows:
                    notes.append(f"sheet {index} cut at {MAX_SHEET_ROWS} rows")
                if cut_cols:
                    notes.append(f"sheet {index} cut at {MAX_SHEET_COLS} columns")
                pages.append(PageText(page_no=len(pages) + 1,
                                      text=_render(rows, ws.title),
                                      source=SOURCE_XLSX, rows=tuple(rows)))
        finally:
            wb.close()
    return Reading(pages=pages, notes=notes)


# ------------------------------------------------------------------ docx


def _parse_bounded(zf: zipfile.ZipFile, name: str,
                   limit: int = MAX_DOCX_XML_BYTES) -> ET.Element:
    """Parse one XML part, refusing an oversized part or any DOCTYPE.

    No DOCTYPE means no entity declaration, so neither an external entity
    (XXE) nor an internal expansion bomb can be defined. The read is capped
    at `limit + 1` bytes whatever the entry declares.
    """
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise InputError("too_large_unpacked",
                         f"{name} declares {info.file_size} bytes, limit {limit}")
    with zf.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise InputError("too_large_unpacked", f"{name} is larger than {limit} bytes")
    if _DOCTYPE.search(data):
        raise InputError("doctype", f"{name} declares a DOCTYPE or entity")
    return ET.fromstring(data)


def refuse_doctype(zf: zipfile.ZipFile) -> None:
    """Refuse the file when ANY XML part declares a DOCTYPE or entity.

    Streamed in blocks with an overlap, so a declaration split across two
    blocks is still seen; bounded by the declared sizes already checked.
    """
    for info in zf.infolist():
        if not info.filename.lower().endswith((".xml", ".rels")):
            continue
        tail = b""
        with zf.open(info) as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    break
                if _DOCTYPE.search(tail + block):
                    raise InputError("doctype", f"{info.filename} declares a DOCTYPE or entity")
                tail = block[-32:]


def _run_text(elem: ET.Element) -> str:
    """A paragraph's text: w:t runs, w:tab as a cell break, w:br as a space."""
    parts: list[str] = []
    for node in elem.iter():
        if node.tag == _W + "t" and node.text:
            parts.append(node.text)
        elif node.tag == _W + "tab":
            parts.append("\t")
        elif node.tag in (_W + "br", _W + "cr") and node.get(_W + "type") != "page":
            parts.append(" ")
    return "".join(parts)


def _has_page_break(elem: ET.Element) -> bool:
    return any(node.tag == _W + "br" and node.get(_W + "type") == "page"
               for node in elem.iter())


def _table_rows(tbl: ET.Element, notes: list[str]) -> list[tuple[str, ...]]:
    """A table's rows as cells, merged cells handled.

    `w:gridSpan` (a cell across columns) is written once. `w:vMerge` without
    `restart` continues the cell above in the same grid column, so its value
    is repeated - the same rule the workbook reader uses for a range that
    spans rows.
    """
    rows: list[tuple[str, ...]] = []
    above: dict[int, str] = {}
    for tr in tbl.findall(_W + "tr"):
        cells: list[str] = []
        grid_col = 0
        for tc in tr.findall(_W + "tc"):
            props = tc.find(_W + "tcPr")
            span = 1
            vmerge = None
            if props is not None:
                gs = props.find(_W + "gridSpan")
                if gs is not None:
                    try:
                        span = max(1, min(int(gs.get(_W + "val") or 1), MAX_SHEET_COLS))
                    except ValueError:
                        span = 1
                vm = props.find(_W + "vMerge")
                if vm is not None:
                    vmerge = vm.get(_W + "val") or "continue"
            text = " ".join(" ".join(_run_text(p).split())
                            for p in tc.iter(_W + "p")).strip()
            text = " ".join(text.split())
            if vmerge == "continue" and not text:
                text = above.get(grid_col, "")
            text = _clip(text, notes, "table")
            above[grid_col] = text
            if text:
                cells.append(text)
            grid_col += span
        if cells:
            rows.append(tuple(cells))
    return rows


def _blocks(body: ET.Element):
    """Paragraphs and tables in DOCUMENT ORDER, looking inside content
    controls (`w:sdt`), which wrap either."""
    for child in body:
        if child.tag in (_W + "p", _W + "tbl"):
            yield child
        elif child.tag == _W + "sdt":
            content = child.find(_W + "sdtContent")
            if content is not None:
                yield from _blocks(content)


def read_docx(path: str | os.PathLike) -> Reading:
    """Paragraphs and tables in document order; a new page at each explicit
    page break. A paragraph's tab stops split it into cells, so a tabbed
    `Design pressure<TAB>15 barg` line is a row like a table row."""
    check_zip_bounds(path)
    notes: list[str] = []
    with zipfile.ZipFile(path) as zf:
        refuse_doctype(zf)
        try:
            root = _parse_bounded(zf, DOCX_REQUIRED_ENTRY)
        except KeyError as exc:
            raise InputError("not_office", "no word/document.xml") from exc
        except ET.ParseError as exc:
            raise InputError("not_office", "word/document.xml is not well-formed") from exc
    body = root.find(_W + "body")
    pages_rows: list[list[tuple[str, ...]]] = [[]]
    count = 0
    for block in _blocks(body if body is not None else root):
        count += 1
        if count > MAX_DOCX_BLOCKS:
            raise InputError("too_many_blocks", f"more than {MAX_DOCX_BLOCKS} paragraphs/rows")
        if block.tag == _W + "tbl":
            pages_rows[-1].extend(_table_rows(block, notes))
            continue
        cells = tuple(c for c in (" ".join(part.split())
                                  for part in _run_text(block).split("\t")) if c)
        if cells:
            pages_rows[-1].append(tuple(_clip(c, notes, "paragraph") for c in cells))
        if _has_page_break(block):
            pages_rows.append([])
    pages = [PageText(page_no=i, text=_render(rows), source=SOURCE_DOCX, rows=tuple(rows))
             for i, rows in enumerate((r for r in pages_rows if r), start=1)]
    return Reading(pages=pages, notes=notes)


# ------------------------------------------------------------------ pdf


def _ocr_page(document_id: str | None, path: str, page_no: int,
              recognise: bool) -> tuple[str, float | None] | None:
    """A scanned page's text through the project's OWN OCR path.

    First what `ocr.py` already stored in `page_ocr` for this document (the
    background recognition the ingest worker runs); only when asked
    (`recognise=True`) is `ocr.recognise_batch` - the same RapidOCR engine,
    vendored models and DPI - run for this one page. No other engine exists.
    """
    if document_id is not None:
        from .db import connect

        row = connect().execute(
            "SELECT text, mean_conf FROM page_ocr WHERE document_id = ?"
            " AND page_no = ? AND char_count > 0", (document_id, page_no)).fetchone()
        if row is not None and row["text"]:
            return row["text"], row["mean_conf"]
    if not recognise:
        return None
    from . import ocr

    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    rows = ocr.recognise_batch(path, sha, [page_no])
    if not rows:
        return None
    _pno, text, mean_conf, *_rest, error = rows[0]
    if error is not None or not (text or "").strip():
        return None
    return text, mean_conf


def read_pdf(path: str | os.PathLike, *, document_id: str | None = None,
             recognise: bool = False) -> Reading:
    """The native text layer per page; a page with none is read by OCR.

    A page with no text layer and no OCR text available stays an EMPTY
    `pdf_text` page: nothing is invented for it.
    """
    import pymupdf

    from .quality import normalise_text

    pages: list[PageText] = []
    with pymupdf.open(str(path)) as doc:
        count = doc.page_count
        native = [normalise_text(doc.load_page(i).get_text("text") or "") for i in range(count)]
    for page_no, text in enumerate(native, start=1):
        if text.strip():
            pages.append(PageText(page_no, text, SOURCE_PDF_TEXT))
            continue
        found = _ocr_page(document_id, str(path), page_no, recognise)
        if found is None:
            pages.append(PageText(page_no, text, SOURCE_PDF_TEXT))
        else:
            ocr_text, conf = found
            pages.append(PageText(page_no, ocr_text, SOURCE_OCR, confidence=conf,
                                  rows=tuple(r for r in (ocr_line_cells(line)
                                             for line in ocr_text.splitlines()) if r)))
    return Reading(pages=pages)


# ------------------------------------------------------------------ entry


def read(path: str | os.PathLike, *, document_id: str | None = None,
         recognise: bool = False) -> Reading:
    """Every page of a datasheet as text, whatever the file is."""
    kind = office_kind(path)
    if kind == KIND_XLSX:
        return read_xlsx(path)
    if kind == KIND_DOCX:
        return read_docx(path)
    return read_pdf(path, document_id=document_id, recognise=recognise)


def page_texts(path: str | os.PathLike, *, document_id: str | None = None,
               recognise: bool = False) -> list[PageText]:
    """`read(path).pages` - the one text every reader of a datasheet uses."""
    return read(path, document_id=document_id, recognise=recognise).pages


@lru_cache(maxsize=8)
def _cached_office(path: str, mtime_ns: int, size: int) -> tuple[PageText, ...]:
    return tuple(read(path).pages)


def office_pages(path: str) -> tuple[PageText, ...]:
    """Pages of an office file, cached per (path, mtime, size): the datasheet
    reader asks page by page and must not re-open the zip for each."""
    st = os.stat(path)
    return _cached_office(str(path), st.st_mtime_ns, st.st_size)


def office_condition(path: str) -> tuple[str | None, str]:
    """(slug, sentence) when an office file cannot be read; (None, "") when it
    reads. The office twin of `datasheets.pdf_condition`."""
    try:
        office_pages(path)
    except FileNotFoundError:
        return "office_missing", "the stored file is not there"
    except InputError as exc:
        return f"office_{exc.code}", f"the stored file was refused: {exc.message}"
    except Exception as exc:  # noqa: BLE001 - any failure to open is the FILE's condition
        return "office_damaged", f"the stored file could not be read ({type(exc).__name__})"
    return None, ""


# ------------------------------------------------------------------ pairs

#: A cell that only names a column ("Value", "Unit") - a header row is not a
#: fact. Generic table vocabulary, not per-document.
_HEADER_WORDS = frozenset({
    "value", "values", "unit", "units", "uom", "remark", "remarks", "note",
    "notes", "description", "parameter", "parameters", "item", "data",
})
_ROW_NUMBER = re.compile(r"^\d{1,3}\.?$")
#: An OCR line split into cells: a pipe, or a run of two or more spaces (a
#: column gap), both of which a table's printed row produces.
_OCR_CELL_SPLIT = re.compile(r"\s*\|\s*|\s{2,}|\t+")


def ocr_line_cells(line: str) -> tuple[str, ...]:
    """A table-shaped OCR line as cells; () when the line has one cell."""
    cells = tuple(c.strip() for c in _OCR_CELL_SPLIT.split(line.strip()) if c.strip())
    return cells if len(cells) >= 2 else ()


#: A value cell that states a quantity: an optional comparator, then a
#: digit. Only such a value takes a unit from its own column - "By Vendor"
#: beside a unit is a blank, and "Cast iron" is not a quantity of anything.
_QUANTITY_START = re.compile(r"^[<>≤≥~±+\-]?\s*\d")


def is_unit_cell(text: str | None) -> bool:
    """Is this CELL nothing but a unit - "m3/h", "kg/h", "kPa(g)", "m3/h
    (USGPM)"? Decided by the ONE shared vocabulary (`claims.is_unit`, whose
    grammar knows compound rates) and `datasheets.primary_unit` for a unit
    with its bracketed alternate; never by a list of this module's own."""
    from . import claims
    from .datasheets import primary_unit

    cell = (text or "").strip()
    if not cell:
        return False
    return claims.is_unit(cell) or primary_unit(cell) is not None


def _value_and_unit(rest: list[tuple[int, str]], unit_col: int | None) -> str | None:
    """The value text of one row's value cells `(column, text)`, with a unit
    that sits in its own cell moved to where every reader expects it: AFTER
    the number ("42 m3/h"), exactly as a PDF grid row's value carries its
    unit. Without this "Flow | m3/h | 42" was read as the value "m3/h 42",
    which parses as no number at all.

    Which cell is the unit: the column a header row named ("Unit", "UOM")
    when this row has a non-numeric cell there - the header is the sheet's
    own word, so even a unit the vocabulary does not know is taken - else
    the ONE value cell `is_unit_cell` recognises (two recognised cells are
    ambiguous and nothing is moved). A unit with no value beside it is no
    fact (None); a non-quantity value ("By Vendor") is kept without it.
    """
    from . import claims
    from .datasheets import measure_value, primary_unit

    if len(rest) < 2:
        # ONE value cell is the value, whatever column it sits in: "Pumped
        # fluid | Water" under a "Unit" header is not a unit with no value.
        return " ".join(text for _col, text in rest)
    at = None
    if unit_col is not None:
        at = next((k for k, (col, text) in enumerate(rest)
                   if col == unit_col and not _QUANTITY_START.match(text)), None)
    if at is None:
        found = [k for k, (_col, text) in enumerate(rest) if is_unit_cell(text)]
        at = found[0] if len(found) == 1 else None
    if at is None:
        return " ".join(text for _col, text in rest)
    unit_text = rest[at][1]
    # A unit the vocabulary knows is kept WHOLE - "kPa(g)" keeps its gauge
    # reference. Only a two-unit cell, "m3/h (USGPM)", drops its alternate.
    unit = unit_text if claims.is_unit(unit_text) else (primary_unit(unit_text) or unit_text)
    value = " ".join(text for k, (_col, text) in enumerate(rest) if k != at)
    if not value:
        return None
    if _QUANTITY_START.match(value) and measure_value(value)[1] is None:
        return f"{value} {unit}"
    return value


def pairs_from_rows(rows) -> list[tuple[str, str]]:
    """(label, value) pairs from table-shaped rows, for the rules reader.

    One row is one field: the first cell is the label, the remaining cells in
    printed order are the value (`Design pressure | 15 | barg` -> ("Design
    pressure", "15 barg"), which `datasheets.measure_value` reads as a number
    and a unit). A leading row number is dropped; a one-cell row is a field
    only when written `LABEL: VALUE`; a row whose value cells only name
    columns ("Value | Unit") is a header, not a fact. The label must pass
    `datasheets.is_field_label`, the rule every other reader applies.

    A UNIT IN ITS OWN CELL goes after the number, whichever side of it it was
    printed on (`Flow | m3/h | 42` and `Flow | 42 | m3/h` -> ("Flow",
    "42 m3/h")), and a header row that names a unit column ("Item | Unit |
    Value") says which column that is for the rows beneath it - see
    `_value_and_unit`. Columns are counted on the row as printed, empty
    cells included, so the header's column is the data rows' column.

    PROVABLE: the label and every value cell are cells of the row, and the row
    is a line of the page text, so each pair is found on the page it cites.
    """
    from .datasheets import is_field_label, is_unit_header

    out: list[tuple[str, str]] = []
    unit_col: int | None = None
    for row in rows:
        cells = [(i, c.strip()) for i, c in enumerate(row) if c and c.strip()]
        if len(cells) >= 3 and _ROW_NUMBER.match(cells[0][1]):
            cells = cells[1:]
        if not cells:
            continue
        if len(cells) == 1:
            if ":" not in cells[0][1]:
                continue
            label, _, value = cells[0][1].partition(":")
            rest = [(cells[0][0], value.strip())] if value.strip() else []
        else:
            label, rest = cells[0][1], cells[1:]
        label = label.strip().rstrip(":").strip()
        if rest and all(c.lower().rstrip(":") in _HEADER_WORDS for _i, c in rest):
            # A HEADER ROW: not a fact, but it may say where the unit is.
            unit_col = next((i for i, c in rest if is_unit_header(c.rstrip(":"))), None)
            continue
        if not rest:
            continue
        value = _value_and_unit(rest, unit_col)
        if value and label and is_field_label(label):
            out.append((label, value))
    return out


def pairs_for_page(path: str, page_no: int) -> list[tuple[str, str]]:
    """The rules reader's pairs for one page of an office file ([] off-range)."""
    pages = office_pages(path)
    if not (1 <= page_no <= len(pages)):
        return []
    return pairs_from_rows(pages[page_no - 1].rows)


def extraction_method(path: str) -> str | None:
    """`xlsx` / `docx` for an office file, None otherwise - recorded on each
    fact as its extraction method, so a fact says what it was read from."""
    kind = office_kind(path)
    return {KIND_XLSX: SOURCE_XLSX, KIND_DOCX: SOURCE_DOCX}.get(kind)


@lru_cache(maxsize=64)
def _kind_cached(path: str, mtime_ns: int, size: int) -> str | None:
    return office_kind(path)


def is_office_input(path: str | None) -> bool:
    """True when DATASHEET_OFFICE_INPUT is on AND `path` is a workbook or Word
    document. The one question every PyMuPDF reader of a datasheet asks
    before opening the file: MuPDF opens an .xlsx too, and reads it badly
    (numbers without their labels), so an office file must never reach it."""
    from .config import settings

    if not path or not settings.datasheet_office_input:
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    return _kind_cached(str(path), st.st_mtime_ns, st.st_size) is not None


def tables_json(page: PageText, text: str) -> str | None:
    """`pages.tables_json` for an office page: each run of consecutive
    multi-cell rows as one table, in the shape `extract.page_tables` stores.

    WHY: the chunker's quality gate drops label/value lines as prose without a
    clause (measured: a whole rendered sheet excluded as `no_clause`), exactly
    as it would a PDF table's cells - a PDF table survives because its rows
    are stored here and kept whole as a table chunk. An office sheet IS a
    table, so it is stored the same way. `text` is the page text as stored
    (normalised); the line indices address it, so a row is claimed only when
    its line there is exactly its rendered row.
    """
    import json

    from . import tables as tables_mod
    from .quality import normalise_text

    lines = text.split("\n")
    rendered = [normalise_text(CELL_SEPARATOR.join(row)) for row in page.rows]
    found: list[dict] = []
    run_rows: list[list[str]] = []
    run_lines: list[int] = []
    cursor = 0

    def flush():
        if len(run_rows) >= tables_mod.MIN_ROWS:
            width = max(len(r) for r in run_rows)
            if tables_mod.MIN_COLUMNS <= width <= tables_mod.MAX_COLUMNS:
                found.append({"bbox": None,
                              "rows": [r + [""] * (width - len(r)) for r in run_rows],
                              "lines": list(run_lines)})
        run_rows.clear()
        run_lines.clear()

    for row, line_text in zip(page.rows, rendered):
        try:
            index = lines.index(line_text, cursor)
        except ValueError:
            flush()
            continue
        if len(row) < 2 or (run_lines and index != run_lines[-1] + 1):
            flush()
        if len(row) >= 2:
            run_rows.append([normalise_text(c) for c in row])
            run_lines.append(index)
        cursor = index + 1
    flush()
    if not found:
        return None
    from .extract import TABLE_READER_VERSION

    return json.dumps({"v": TABLE_READER_VERSION, "tables": found},
                      ensure_ascii=False, separators=(",", ":"))
