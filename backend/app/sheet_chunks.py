"""Chunks for an Excel workbook, cited by sheet and cell range (#525 slice 2).

With `intake.uploads_enabled()` (INTAKE_IMAGES_XLSX_ENABLED and
ONE_INTAKE_ENABLED) a workbook upload is indexed. Its pages are its visible
sheets, read by `intake.read_sheet`; its chunks are built here from the same
cells with their positions kept, so every chunk carries a `locator` such as
`'Line list'!A3:F17`: the sheet and the cell range its rows came from. A
citation of a workbook chunk shows that locator (the same column a Word chunk
uses for "4.2 > para 3"), so a claim resolves to cells an engineer can open.

EXACT RANGES. A chunk holds whole rows, and its locator names exactly those
rows and the columns from the first to the last value they hold; every row is
written as one cell per column of that range, so the chunk's text IS the text
of the cells it cites. A chunk never starts or ends inside a row. A row too
long for one chunk is cut between cells, each piece citing its own cells; only
a single cell too long for a chunk is cut inside the cell, and its pieces say
so (`Notes!A1 (part 1 of 3)`).

THE DISPLAYED VALUE. A cell is quoted as Excel shows it, from its number
format: `0.0%` of 0.125 is `12.5%`, `#,##0.00` of 1234.5 is `1,234.50`, a
date as its format writes it, quoted text and currency signs kept. A format
this reader does not understand (fractions, scientific, conditional colours)
falls back to the stored value, written as `datasheet_inputs` writes it.
(The sheet's page text, `datasheet_inputs.read_xlsx`, keeps the stored value:
the datasheet reader is unchanged by this slice.)

MERGED CELLS as `datasheet_inputs.read_xlsx` reads them: a range spanning
several rows repeats its value on each of its rows in its first column, so a
label merged down beside three values labels all three.

FAIL-CLOSED ON ROLE (lead decisions on #1560). An uploaded workbook is stored
and NOT indexed until a person sets its role (`withhold`, page-0 reason
"waiting for its role before indexing"); setting a role queues it for
indexing (`status_after_role`). A CRS template is a form to fill, not content
to answer from: one classified CRS_TEMPLATE is never indexed, and one that was
indexed under another role leaves the index when the role changes. Indexing
templates needs the owner's approval.

Nothing is left out in silence. The limits are the workbook reader's own
(`datasheet_inputs.MAX_SHEET_ROWS`, `MAX_SHEET_COLS`, `MAX_CELL_CHARS`), and
what they cut, a hidden sheet, an empty sheet and a formula with no stored
result are stored as intake reasons (`intake.store`), which the document's
coverage and the CRS note 'File not fully read' show.

General: no sheet name, label or layout is recognised (rule 13). Local only,
no model, no socket.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import date, datetime, time

from . import chunker
from .chunker import Block, count_tokens
from .config import settings

#: A sheet name Excel writes without quotes in a reference.
_PLAIN_SHEET = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
CRS_TEMPLATE = "CRS_TEMPLATE"


def applies(path: str | os.PathLike) -> bool:
    """True when this stored file is a workbook to be chunked here (switch on)."""
    from . import intake

    if not intake.uploads_enabled():
        return False
    try:
        return intake.detect(path) == intake.KIND_SHEET
    except (OSError, intake.IntakeRefused):
        return False


def structured(doc) -> Callable[[], list[Block]] | None:
    """The chunk builder for a document that states its own structure, else None:
    a Word document (pagination 'flow', `docx_chunks`) or, switch on, a workbook (here).
    Returned unbuilt, so a document whose chunks are unchanged is not read again."""
    from . import docx_chunks, docx_reader, stored_paths

    path = stored_paths.local(doc["stored_path"])
    if dict(doc).get("pagination") == "flow":
        return lambda: docx_chunks.build_chunks(docx_reader.read_structure(path))
    return (lambda: build_chunks(path)) if applies(path) else None


#: Page-0 intake reasons of a workbook held out of the index (lead decision, #1560).
WHY_WAITING = (
    "not indexed yet: waiting for its role before indexing (a workbook is indexed"
    " only once a person sets what it is)"
)
WHY_TEMPLATE = "not indexed: a CRS template is a form to fill, not content to cite"


def _held(conn, document_id: str):
    """(stored_path, role) of a slice-2 workbook whose role does not allow
    indexing (none yet, or CRS_TEMPLATE); None for anything else."""
    from . import stored_paths

    doc = conn.execute(
        "SELECT d.stored_path, c.document_role FROM documents d LEFT JOIN"
        " document_classification c ON c.document_id = d.id WHERE d.id = ?",
        (document_id,),
    ).fetchone()
    if doc is None or not applies(stored_paths.local(doc["stored_path"])):
        return None
    role = doc["document_role"]
    return None if role and role != CRS_TEMPLATE else (doc["stored_path"], role)


def withhold(document_id: str) -> bool:
    """FAIL-CLOSED: a workbook read by this slice is indexed only once a person
    has set its role, and never as a CRS_TEMPLATE. Until then, or as a
    template, it holds no chunks, keyword rows or vectors, it is
    `stored_not_indexed` (stored and listed, not retrievable), its extraction
    job is closed (cancelled), and page 0 of its intake reasons says why.
    True when it is held. Anything else: untouched."""
    from . import fts_index, job_queue, states
    from .db import connect

    conn = connect()
    held = _held(conn, document_id)
    if held is None:
        return False
    fts_index.ensure_schema(conn)  # the keyword table is made on first use
    why = WHY_TEMPLATE if held[1] == CRS_TEMPLATE else WHY_WAITING
    with conn:
        for table in (
            "chunks_fts",
            "chunk_vectors",
            "chunks",
            "intake_blocks",
            "intake_reasons",
        ):
            conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
        conn.execute(
            "INSERT INTO intake_reasons (document_id, page_no, code, reason)"
            " VALUES (?, 0, 'not_indexed', ?)",
            (document_id, why),
        )
        conn.execute(
            "UPDATE documents SET status = ?, chunk_count = 0, chunk_count_total = 0,"
            " embedded_count = 0 WHERE id = ?",
            (states.STORED_NOT_INDEXED, document_id),
        )
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE document_id = ?"
            " AND stage IN ('extract', 'chunk') AND state NOT IN (?, ?, ?)",
            (
                job_queue.CANCELLED,
                job_queue.now_iso(),
                document_id,
                job_queue.DONE,
                job_queue.CANCELLED,
                job_queue.POISONED,
            ),
        )
    return True


def status_after_role(document_id: str):
    """For a role change: a held workbook stays held (None); a workbook whose
    role now allows it is queued for indexing (None: it is not READY); else
    the document's `status` row, for the READY hooks."""
    from . import job_queue, states
    from .db import connect

    if withhold(document_id):
        return None
    conn = connect()
    row = conn.execute(
        "SELECT status, stored_path, priority FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    waiting = conn.execute(
        "SELECT 1 FROM intake_reasons WHERE document_id = ? AND code = 'not_indexed'",
        (document_id,),
    ).fetchone()
    if row is None or row["status"] != states.STORED_NOT_INDEXED or not waiting:
        return row
    now = job_queue.now_iso()
    with conn:
        conn.execute("DELETE FROM intake_reasons WHERE document_id = ?", (document_id,))
        conn.execute(
            "UPDATE documents SET status = ? WHERE id = ?", (states.QUEUED, document_id)
        )
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,"
            " priority) VALUES (?, ?, 'extract', 'running', ?, ?, ?)",
            (f"job_{os.urandom(6).hex()}", document_id, now, now, row["priority"]),
        )
    return None


def cell_range(
    sheet: str, first_row: int, first_col: int, last_row: int, last_col: int
) -> str:
    """`'Sheet name'!A3:F17` (or `Data!B2` for one cell), quoted as Excel quotes it."""
    from openpyxl.utils import get_column_letter

    name = (
        sheet if _PLAIN_SHEET.fullmatch(sheet) else "'" + sheet.replace("'", "''") + "'"
    )
    start = f"{get_column_letter(first_col)}{first_row}"
    end = f"{get_column_letter(last_col)}{last_row}"
    return f"{name}!{start}" if start == end else f"{name}!{start}:{end}"


# ------------------------------------------------------------ displayed value

_QUOTED = re.compile(r'"([^"]*)"|\\(.)|\[\$([^\]-]*)[^\]]*\]|\[[^\]]*\]|[_*].')
#: The digit placeholders of an Excel FORMAT CODE (`#,##0.00`), which say how many
#: decimals to show. It never reads a value: the value is already a number from
#: openpyxl, and document text is read by `numparse`.
_FORMAT_PLACEHOLDERS = re.compile(r"[#0?][#0?,]*(?:\.[#0?]+)?")
_DATE_TOKEN = re.compile(r"(?i)yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|am/pm")


def _protect(fmt: str) -> tuple[str, list[str]]:
    """The format's codes, with its quoted text, escapes and [$sym] set aside as
    placeholders (private-use characters no code pattern matches)."""
    kept: list[str] = []

    def keep(m: re.Match) -> str:
        kept.append(next((g for g in m.groups() if g is not None), ""))
        return chr(0xE000 + len(kept) - 1)

    return _QUOTED.sub(keep, fmt), kept


def _restore(text: str, kept: list[str]) -> str:
    return re.sub("[\ue000-\uf8ff]", lambda m: kept[ord(m.group(0)) - 0xE000], text)


def _shown_number(value: float, fmt: str) -> str | None:
    sections = fmt.split(";")
    section = sections[0]
    if value < 0 and len(sections) > 1:  # a negative section writes its own sign
        section, value = sections[1], -value
    code, kept = _protect(section)
    m = _FORMAT_PLACEHOLDERS.search(code)
    if not m or re.search(r"[eE][+-]|/", code):
        return None
    spec = m.group(0)
    places = len(spec.split(".")[1]) if "." in spec else 0
    scaled = value * 100 if "%" in code else value
    number = f"{scaled:,.{places}f}" if "," in spec else f"{scaled:.{places}f}"
    return _restore(code[: m.start()] + number + code[m.end() :], kept)


def _shown_date(value, fmt: str) -> str | None:
    text, kept = _protect(fmt.split(";")[0])
    if not _DATE_TOKEN.search(text):
        return None
    tokens = list(_DATE_TOKEN.finditer(text))
    twelve = any(t.group(0).lower() == "am/pm" for t in tokens)
    out, at = [], 0
    for i, t in enumerate(tokens):
        out.append(text[at : t.start()])
        at = t.end()
        tok = t.group(0)
        low = tok.lower()
        near_time = (i and tokens[i - 1].group(0).lower() in ("h", "hh")) or (
            i + 1 < len(tokens) and tokens[i + 1].group(0).lower() in ("s", "ss")
        )
        out.append(_date_part(value, low, tok, twelve, near_time))
    out.append(text[at:])
    return _restore("".join(out), kept)


def _date_part(value, low: str, tok: str, twelve: bool, minutes: bool) -> str:
    hour = getattr(value, "hour", 0)
    parts = {
        "yyyy": lambda: f"{value.year:04d}",
        "yy": lambda: f"{value.year % 100:02d}",
        "mmmm": lambda: value.strftime("%B"),
        "mmm": lambda: value.strftime("%b"),
        "dddd": lambda: value.strftime("%A"),
        "ddd": lambda: value.strftime("%a"),
        "dd": lambda: f"{value.day:02d}",
        "d": lambda: str(value.day),
        "hh": lambda: f"{(hour % 12 or 12) if twelve else hour:02d}",
        "h": lambda: str((hour % 12 or 12) if twelve else hour),
        "ss": lambda: f"{getattr(value, 'second', 0):02d}",
        "s": lambda: str(getattr(value, "second", 0)),
        "am/pm": lambda: "AM" if hour < 12 else "PM",
    }
    if low in ("mm", "m"):
        if minutes:
            minute = getattr(value, "minute", 0)
            return f"{minute:02d}" if low == "mm" else str(minute)
        return f"{value.month:02d}" if low == "mm" else str(value.month)
    try:
        return parts[low]()
    except (AttributeError, ValueError):
        return tok


def shown(value, fmt: str | None) -> str:
    """The cell as Excel displays it (see the module note); else the stored value."""
    from . import datasheet_inputs as di

    raw = di._cell_text(value)
    if not raw or not fmt or fmt in ("General", "@") or isinstance(value, bool):
        return raw
    if isinstance(value, (int, float)):
        out = _shown_number(float(value), fmt)
    elif isinstance(value, (datetime, date, time)):
        out = _shown_date(value, fmt)
    else:
        out = None
    return " ".join(out.split()) if out else raw


# ---------------------------------------------------------------- the rows

Row = tuple[int, dict[int, str]]


def _merges(zf, sheet_xml: str | None) -> tuple[dict, set]:
    """(carried, corners) as `read_xlsx` builds them: a cell below a range's first
    row in its first column -> that range's top-left cell."""
    from . import datasheet_inputs as di

    merged = di._merged_ranges(zf, sheet_xml) if sheet_xml else []
    carried: dict[tuple[int, int], tuple[int, int]] = {}
    for r0, c0, r1, _c1 in merged:
        for r in range(r0 + 1, min(r1, di.MAX_SHEET_ROWS) + 1):
            carried[(r, c0)] = (r0, c0)
        if len(carried) > di.MAX_TOTAL_CELLS:
            raise di.InputError("too_many_cells", "merged ranges cover too many cells")
    return carried, {(r0, c0) for r0, c0, *_ in merged}


def _sheet_rows(ws, carried: dict, corners: set) -> list[Row]:
    """(row number, {column: displayed text}) for each row holding a value."""
    from . import datasheet_inputs as di

    out: list[Row] = []
    top_left: dict[tuple[int, int], str] = {}
    for row_no, row in enumerate(ws.iter_rows(), start=1):
        if row_no > di.MAX_SHEET_ROWS:
            break
        cells: dict[int, str] = {}
        for col_no, cell in enumerate(row[: di.MAX_SHEET_COLS], start=1):
            value = getattr(cell, "value", None)
            fmt = getattr(cell, "number_format", None)
            text = shown(value, fmt)[: di.MAX_CELL_CHARS]
            if (row_no, col_no) in corners:
                top_left[(row_no, col_no)] = text
            if not text and (row_no, col_no) in carried:
                text = top_left.get(carried[(row_no, col_no)], "")
            if text:
                cells[col_no] = text
        if cells:
            out.append((row_no, cells))
    return out


def _md(cells: dict[int, str], first: int, last: int) -> str:
    """One row as `| a |  | c |`, a cell per column from `first` to `last`."""
    return chunker._md_row([cells.get(c, "") for c in range(first, last + 1)], 0)


def _render(title: str, group: list[Row]) -> tuple[str, str]:
    """(text, locator) of whole rows: exactly the cells the locator names."""
    first = min(min(cells) for _r, cells in group)
    last = max(max(cells) for _r, cells in group)
    text = "\n".join([title] + [_md(cells, first, last) for _r, cells in group])
    return text, cell_range(title, group[0][0], first, group[-1][0], last)


def _block(title: str, page_no: int, text: str, locator: str) -> Block:
    b = Block("table", text, page_no, page_no, title, count_tokens(text))
    b.locator, b.context = locator, title
    return b


def _split_row(title: str, page_no: int, row: Row, ceiling: int) -> list[Block]:
    """A row too long for one chunk: cut between cells, each piece its own cells."""
    row_no, cells = row
    out: list[Block] = []
    piece: dict[int, str] = {}
    for col in sorted(cells):
        trial = {**piece, col: cells[col]}
        if piece and count_tokens(_render(title, [(row_no, trial)])[0]) > ceiling:
            out.append(_block(title, page_no, *_render(title, [(row_no, piece)])))
            trial = {col: cells[col]}
        if count_tokens(_render(title, [(row_no, trial)])[0]) > ceiling:
            out.extend(_split_cell(title, page_no, row_no, col, cells[col], ceiling))
            piece = {}
            continue
        piece = trial
    if piece:
        out.append(_block(title, page_no, *_render(title, [(row_no, piece)])))
    return out


def _split_cell(title, page_no, row_no, col, text, ceiling) -> list[Block]:
    """One cell too long for a chunk: cut between words, each part named as a part."""
    where = cell_range(title, row_no, col, row_no, col)
    parts: list[list[str]] = [[]]
    for word in text.split():
        if parts[-1] and count_tokens(_md({1: " ".join(parts[-1] + [word])}, 1, 1)) > (
            ceiling - count_tokens(title) - 8
        ):
            parts.append([])
        parts[-1].append(word)
    n = len(parts)
    return [
        _block(
            title,
            page_no,
            f"{title}\n{_md({1: ' '.join(p)}, 1, 1)}",
            where if n == 1 else f"{where} (part {i} of {n})",
        )
        for i, p in enumerate(parts, start=1)
    ]


def _sheet_chunks(title: str, page_no: int, rows: list[Row]) -> list[Block]:
    """Whole rows per chunk, the budget counted on exactly the text written."""
    target, ceiling = settings.chunk_target_tokens, settings.chunk_max_tokens
    chunks: list[Block] = []
    group: list[Row] = []
    for row in rows:
        if count_tokens(_render(title, [row])[0]) > ceiling:
            if group:
                chunks.append(_block(title, page_no, *_render(title, group)))
                group = []
            chunks.extend(_split_row(title, page_no, row, ceiling))
            continue
        if group and count_tokens(_render(title, [*group, row])[0]) > target:
            chunks.append(_block(title, page_no, *_render(title, group)))
            group = []
        group.append(row)
    if group:
        chunks.append(_block(title, page_no, *_render(title, group)))
    return chunks


def build_chunks(path: str | os.PathLike) -> list[Block]:
    """Every visible sheet's rows as `table` chunks; page N is the Nth visible sheet,
    the numbering `datasheet_inputs.read_xlsx` (and so the stored pages) uses."""
    import zipfile

    import openpyxl

    from . import datasheet_inputs as di

    di.check_zip_bounds(path)
    chunks: list[Block] = []
    with zipfile.ZipFile(path) as zf:
        di.refuse_doctype(zf)
        sheet_xml = di._sheet_paths(zf)
        wb = openpyxl.load_workbook(
            path, read_only=True, data_only=True, keep_links=False
        )
        try:
            page_no = 0
            for ws in wb.worksheets:
                if getattr(ws, "sheet_state", "visible") != "visible":
                    continue  # stored as an intake reason, never read
                page_no += 1
                carried, corners = _merges(zf, sheet_xml.get(ws.title))
                rows = _sheet_rows(ws, carried, corners)
                chunks.extend(_sheet_chunks(ws.title, page_no, rows))
        finally:
            wb.close()
    return chunks
