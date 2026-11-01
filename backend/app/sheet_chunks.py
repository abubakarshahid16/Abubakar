"""Chunks for an Excel workbook, cited by sheet and cell range (#525 slice 2).

With `intake.uploads_enabled()` (INTAKE_IMAGES_XLSX_ENABLED and
ONE_INTAKE_ENABLED) a workbook upload is indexed. Its pages are its visible
sheets, read by `intake.read_sheet`; its chunks are built here from the same
cells with their positions kept, so every chunk carries a `locator` such as
`'Line list'!A3:F17`: the sheet and the cell range its rows came from. A
citation of a workbook chunk shows that locator (the same column a Word chunk
uses for "4.2 > para 3"), so a claim resolves to cells an engineer can open.

Nothing is left out in silence. The limits are the workbook reader's own
(`datasheet_inputs.MAX_SHEET_ROWS`, `MAX_SHEET_COLS`, `MAX_CELL_CHARS`), and
what they cut, a hidden sheet, an empty sheet and a formula with no stored
result are already stored as intake reasons (`intake.store`), which the
document's coverage and the CRS note 'File not fully read' show. A merged
range's value is written once, at its top-left cell, which is where the
citation points.

General: no sheet name, label or layout is recognised (rule 13). Local only,
no model, no socket.
"""

from __future__ import annotations

import os
import re

from . import chunker
from .chunker import Block, count_tokens
from .config import settings

#: A sheet name Excel writes without quotes in a reference.
_PLAIN_SHEET = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def applies(path: str | os.PathLike) -> bool:
    """True when this stored file is a workbook to be chunked here (switch on)."""
    from . import intake

    if not intake.uploads_enabled():
        return False
    try:
        return intake.detect(path) == intake.KIND_SHEET
    except (OSError, intake.IntakeRefused):
        return False


def cell_range(sheet: str, first_row: int, first_col: int, last_row: int, last_col: int) -> str:
    """`'Sheet name'!A3:F17` (or `Data!B2` for one cell), quoted as Excel quotes it."""
    from openpyxl.utils import get_column_letter

    name = sheet if _PLAIN_SHEET.fullmatch(sheet) else "'" + sheet.replace("'", "''") + "'"
    start = f"{get_column_letter(first_col)}{first_row}"
    end = f"{get_column_letter(last_col)}{last_row}"
    return f"{name}!{start}" if start == end else f"{name}!{start}:{end}"


Row = tuple[int, dict[int, str]]


def _sheet_rows(ws) -> list[Row]:
    """(row number, {column: text}) for each row holding a value, within the limits."""
    from . import datasheet_inputs as di

    out: list[Row] = []
    for row_no, values in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_no > di.MAX_SHEET_ROWS:
            break
        cells = [
            (col_no, di._cell_text(v)[: di.MAX_CELL_CHARS])
            for col_no, v in enumerate(values[: di.MAX_SHEET_COLS], start=1)
        ]
        cells = {c: t for c, t in cells if t}
        if cells:
            out.append((row_no, cells))
    return out


def _md(cells: dict[int, str], first: int, last: int) -> str:
    """One row as `| a |  | c |`, a cell per column from `first` to `last`, so
    every row of a chunk lines up with the cell range its locator names."""
    return chunker._md_row([cells.get(c, "") for c in range(first, last + 1)], 0)


def _sheet_chunks(title: str, page_no: int, rows: list[Row]) -> list[Block]:
    target, ceiling = settings.chunk_target_tokens, settings.chunk_max_tokens
    head_tokens = count_tokens(title)
    chunks: list[Block] = []
    group: list[Row] = []
    tokens = head_tokens

    def flush() -> None:
        nonlocal group, tokens
        if not group:
            return
        first = min(min(cells) for _r, cells in group)
        last = max(max(cells) for _r, cells in group)
        where = cell_range(title, group[0][0], first, group[-1][0], last)
        text = "\n".join([title] + [_md(cells, first, last) for _r, cells in group])
        pieces = (
            [Block("table", text, page_no, page_no, title, count_tokens(text))]
            if count_tokens(text) <= ceiling
            else chunker.split_oversized(text, page_no, page_no, title, "table")
        )
        for piece in pieces:  # an over-long row is windowed, every window keeps its cells
            piece.locator, piece.context = where, title
            chunks.append(piece)
        group, tokens = [], head_tokens

    for row in rows:
        t = count_tokens(_md(row[1], min(row[1]), max(row[1])))
        if group and tokens + t > target:
            flush()
        group.append(row)
        tokens += t
    flush()
    return chunks


def build_chunks(path: str | os.PathLike) -> list[Block]:
    """Every visible sheet's rows as `table` chunks; page N is the Nth visible sheet,
    the numbering `datasheet_inputs.read_xlsx` (and so the stored pages) uses."""
    import zipfile

    import openpyxl

    from . import datasheet_inputs as di

    di.check_zip_bounds(path)
    with zipfile.ZipFile(path) as zf:
        di.refuse_doctype(zf)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    chunks: list[Block] = []
    try:
        page_no = 0
        for ws in wb.worksheets:
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue  # stored as an intake reason, never read
            page_no += 1
            chunks.extend(_sheet_chunks(ws.title, page_no, _sheet_rows(ws)))
    finally:
        wb.close()
    return chunks
