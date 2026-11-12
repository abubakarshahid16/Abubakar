"""The one CRS layout (order 13, owner 12 Nov 2026): the drawing code both reviewers' workbooks share.

`crs_export` is the app's CRS exporter and keeps the normal reviewer's content (the view, the rows, the numbers). This module holds what
makes the two reviewers' sheets look alike, STYLED BY CODE and never by hand: the header row, frozen panes and print setup the normal
reviewer's sheet also gets (`style_header_and_print`), and the whole workbook of the AI reviewer (`build_layout_crs`): sheet "CRS"
with the company columns plus a short Status, "Not reviewed or not applicable", "Evidence", "Notes". The caller decides what every cell
SAYS (`agent_review_crs`, `crs_ai_workbook`); this code decides fonts, fills, borders, widths, freeze and print setup, and never
what a cell holds. A string is always stored as text (`crs_export._write`): a cell starting with "=" is never a formula.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from .crs_export import (
    ARIAL,
    BOX,
    HEADERS,
    MAX_ROW_HEIGHT,
    PRIORITY_COLUMN,
    STANDARD_COLUMN,
    SUBTITLE,
    _write,
)

LAYOUT_COLUMNS = (*HEADERS, STANDARD_COLUMN, PRIORITY_COLUMN, "Status")
LAYOUT_WIDTHS = (9.0, 26.0, 14.0, 90.0, 22.0, 24.0, 16.0, 24.0, 11.0, 13.0)
LAYOUT_MAIN_SHEET = "CRS"
EVIDENCE_SHEET = "Evidence"
NOTES_SHEET = "Notes"
#: One light fill per Status, defined ONCE (four colours; the hex values are the pale fills the sheet already uses).
STATUS_FILLS = {
    "Fail": PatternFill("solid", fgColor="FFF5D6D6"),
    "AI opinion": PatternFill("solid", fgColor="FFEFE8F7"),
    "Query": PatternFill("solid", fgColor="FFFCF3CF"),
    "Pass": PatternFill("solid", fgColor="FFE3F2E6"),
}
HEADER_FILL = PatternFill("solid", fgColor="FF1F3864")
HEADER_FONT = Font(name=ARIAL, bold=True, size=10, color="FFFFFFFF")
HEADING_FILL = PatternFill("solid", fgColor="FFD9E1F2")
CHARS_PER_WIDTH = (
    1.15  # characters that fit in one line per unit of column width (Arial 10)
)


def _lines_needed(value, width: float) -> int:
    text = "" if value is None else str(value)
    per_line = max(4, int(width * CHARS_PER_WIDTH))
    return sum(max(1, -(-len(part) // per_line)) for part in text.split("\n"))


def style_header_row(ws, header_row: int, ncols: int) -> None:
    """The header row of a table sheet: bold white text on the header fill, centred, wrapped, boxed."""
    for col in range(1, ncols + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = BOX


def style_print(ws, header_row: int, ncols: int, last_row: int) -> None:
    """Frozen panes under the header row, landscape and one page wide, the header row repeated on every printed page, the
    print area set. Both reviewers' sheets get it."""
    ws.freeze_panes = f"A{header_row + 1}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.print_area = f"A1:{get_column_letter(ncols)}{max(last_row, header_row)}"


def style_header_and_print(ws, header_row: int, ncols: int) -> None:
    """The normal reviewer's sheet: the shared header row, frozen panes and print setup; its rows and their styles are untouched."""
    style_header_row(ws, header_row, ncols)
    style_print(ws, header_row, ncols, ws.max_row)


def style_table(ws, header_row: int, ncols: int, last_row: int, widths=None) -> None:
    """THE styling of a table sheet of the AI reviewer's workbook: `style_header_row`, thin borders on every used cell (every
    cell of the table, an empty Response cell included), wrapped text, column widths, then `style_print`."""
    for i, width in enumerate(widths or (), start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    style_header_row(ws, header_row, ncols)
    for r in range(1, last_row + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            if cell.value is None and r < header_row:
                continue  # an empty cell of the header block above the table is not a used cell
            cell.border = BOX
            if r > header_row:
                cell.alignment = Alignment(
                    horizontal=cell.alignment.horizontal, vertical="top", wrap_text=True
                )
    style_print(ws, header_row, ncols, last_row)


def _table_sheet(ws, columns, rows, widths, heading_rows=(), top=1, statuses=None):
    """Write a header row at `top` and the rows below it; return the last row. `statuses` (one per row) picks the fill."""
    for c, name in enumerate(columns, start=1):
        _write(ws, top, c, name)
    for n, values in enumerate(rows, start=1):
        r = top + n
        for c, value in enumerate(values, start=1):
            _write(ws, r, c, value)
        fill = (
            STATUS_FILLS.get((statuses or [None] * n)[n - 1] or "")
            if statuses
            else None
        )
        if fill is not None:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).fill = fill
        if (n - 1) in heading_rows:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).fill = HEADING_FILL
                ws.cell(row=r, column=c).font = Font(name=ARIAL, bold=True, size=10)
        else:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).font = Font(name=ARIAL, size=10)
        height = max(_lines_needed(v, widths[c]) for c, v in enumerate(values)) * 13
        ws.row_dimensions[r].height = min(MAX_ROW_HEIGHT, max(15, height))
    last = top + len(rows)
    style_table(ws, top, len(columns), last, widths)
    return last


def _put(ws, row, col, value, bold=False, size=10, center=False, wrap=False):
    cell = _write(ws, row, col, value)
    cell.font = Font(name=ARIAL, bold=bold, size=size)
    cell.alignment = Alignment(
        horizontal="center" if center else "left", vertical="top", wrap_text=wrap
    )
    return cell


def _header_block(ws, view: dict, ncols: int) -> int:
    """Rows 1 and 2 (title, subtitle), the header facts, the generated-by sentence; returns the row of the table's header."""
    last = get_column_letter(ncols)
    ws.merge_cells(f"A1:{last}1")
    _put(ws, 1, 1, view.get("title") or "", bold=True, size=12, center=True, wrap=True)
    ws.row_dimensions[1].height = 30
    ws.merge_cells(f"A2:{last}2")
    _put(ws, 2, 1, view.get("subtitle") or SUBTITLE, bold=True, size=12, center=True)
    row = 3
    for label, value in view.get("header") or []:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=ncols)
        _put(ws, row, 1, label, bold=True)
        _put(ws, row, 3, value or "", wrap=True)
        ws.row_dimensions[row].height = max(
            15, 13 * _lines_needed(value, sum(LAYOUT_WIDTHS[2:]))
        )
        row += 1
    if view.get("sentence"):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        _put(ws, row, 1, view["sentence"], bold=True)
        row += 1
    return row + 1  # one blank row between the block and the table


def build_layout_crs(view: dict) -> bytes:
    """Draw the CRS of the AI reviewer into the app's layout and return the workbook bytes.

    view (all plain values, decided by the caller; a missing part prints nothing):
      title, subtitle          rows 1 and 2 (merged)
      header                   [(label, value)] rows above the table (a blank value prints blank)
      sentence                 the line under the header block ('Generated by AI, ...')
      rows, statuses           the item rows (10 values each, LAYOUT_COLUMNS order) and each row's Status (its fill)
      other                    {name, columns, rows, widths} the sheet of lines that are not item rows, or None
      evidence                 {columns, rows, statuses, widths} or None (internal copy only)
      notes                    {columns, rows, heading_rows, widths} or None (internal copy only)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = LAYOUT_MAIN_SHEET
    ncols = len(LAYOUT_COLUMNS)
    header_row = _header_block(ws, view, ncols)
    for c, name in enumerate(LAYOUT_COLUMNS, start=1):
        _write(ws, header_row, c, name)
    rows, statuses = view.get("rows") or [], view.get("statuses") or []
    for n, values in enumerate(rows, start=1):
        r = header_row + n
        for c, value in enumerate(values, start=1):
            _put(ws, r, c, value, center=c in (1, 9, 10), wrap=True)
        fill = STATUS_FILLS.get(statuses[n - 1]) if n - 1 < len(statuses) else None
        if fill is not None:
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).fill = fill
        height = (
            max(_lines_needed(v, LAYOUT_WIDTHS[c]) for c, v in enumerate(values)) * 13
        )
        ws.row_dimensions[r].height = min(MAX_ROW_HEIGHT, max(15, height))
    style_table(ws, header_row, ncols, header_row + len(rows), LAYOUT_WIDTHS)

    other = view.get("other")
    if other:
        _table_sheet(
            wb.create_sheet(other["name"]),
            other["columns"],
            other["rows"],
            other["widths"],
        )
    evidence = view.get("evidence")
    if evidence:
        _table_sheet(wb.create_sheet(EVIDENCE_SHEET), evidence["columns"], evidence["rows"], evidence["widths"],
                     statuses=evidence.get("statuses"))  # fmt: skip
    notes = view.get("notes")
    if notes:
        _table_sheet(wb.create_sheet(NOTES_SHEET), notes["columns"], notes["rows"], notes["widths"],
                     heading_rows=notes.get("heading_rows") or ())  # fmt: skip
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
