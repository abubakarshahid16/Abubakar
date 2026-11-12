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
#: One light fill per Status, defined ONCE (five colours; the hex values are the pale fills the sheet already uses).
STATUS_FILLS = {
    "Fail": PatternFill("solid", fgColor="FFF5D6D6"),
    "AI verdict": PatternFill("solid", fgColor="FFD8EEF0"),
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


def _below(ws, below, last_row: int, ncols: int) -> None:
    """Notes under the table, each `(offset, label, text, column[, height])` at `last_row + offset`: a labelled line (label in A:B, text in
    C to the end), or a notice merged from `column` (1 = across the sheet, 3 = never in column A: a reply is read by the Item No
    there). The print area then reaches the last of them."""
    end = last_row
    for offset, label, text, col, *height in below:
        row = last_row + offset
        end = max(end, row)
        if label:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            _put(ws, row, 1, label, bold=True)
            col = 3
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=ncols)
        _put(ws, row, col, text, bold=bool(label) or col == 1, wrap=True)
        fitted = max(15, 13 * _lines_needed(text, sum(LAYOUT_WIDTHS)))
        ws.row_dimensions[row].height = height[0] if height else fitted
    if end > last_row:
        ws.print_area = f"A1:{get_column_letter(ncols)}{end}"


def engine_rows(facts) -> list[tuple[str, str]]:
    """The header facts that name the ENGINE (12 Nov 2026, owner decision, #1584) and, for a kind not scored against a key, the draft
    sentence, as (label, value). ONE home for both reviewers' sheets and both copies; a fact that is not there adds nothing. The AI
    reviewer's sheet prints them as header rows (`engine_rows`); the normal reviewer's sheet, whose row geometry is pinned, as
    lines of its title cell (`engine_lines`): the same words."""
    got = facts or {}
    rows = []
    if got.get("reviewed_by"):
        rows.append(("Reviewed by:", str(got["reviewed_by"])))
    if got.get("draft_note"):
        rows.append(("Note:", str(got["draft_note"])))
    return rows


def engine_lines(facts) -> list[str]:
    """`engine_rows` as one line each ("Reviewed by: rule check on the local model")."""
    return [f"{label} {value}" for label, value in engine_rows(facts)]


def _header_block(ws, view: dict, ncols: int) -> int:
    """Rows 1 and 2 (title, subtitle), the header facts, the generated-by sentence; returns the row of the table's header."""
    last = get_column_letter(ncols)
    ws.merge_cells(f"A1:{last}1")
    _put(ws, 1, 1, view.get("title") or "", bold=True, size=12, center=True, wrap=True)
    ws.row_dimensions[1].height = view.get("title_height") or 30
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
    if (
        view.get("sentence") is not None
    ):  # "" reserves the row (the normal reviewer's issue copy keeps one geometry)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        _put(ws, row, 1, view["sentence"], bold=True)
        row += 1
    return (
        row + view.get("gap", 1)
    )  # one blank row between the block and the table (a contractor copy: none, as before)


def layout_workbook(view: dict) -> Workbook:
    """Draw a CRS (either reviewer) into the app's one layout and return the workbook.

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
    columns = tuple(
        view.get("columns") or LAYOUT_COLUMNS
    )  # a contractor-facing copy: the nine company columns, no Status
    ncols = len(columns)
    header_row = _header_block(ws, view, ncols)
    for c, name in enumerate(columns, start=1):
        _write(ws, header_row, c, name)
    rows, statuses = view.get("rows") or [], view.get("statuses") or []
    for n, values in enumerate(rows, start=1):
        r = header_row + n
        for c, value in enumerate(values, start=1):
            _put(
                ws,
                r,
                c,
                value,
                center=columns[c - 1] in ("Item No", "Priority", "Status"),
                wrap=True,
            )
        fill = STATUS_FILLS.get(statuses[n - 1]) if n - 1 < len(statuses) else None
        if fill is not None and not view.get(
            "plain"
        ):  # plain: no colour encodes an internal judgement
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).fill = fill
        height = (
            max(
                _lines_needed(v, (view.get("widths") or LAYOUT_WIDTHS)[c])
                for c, v in enumerate(values)
            )
            * 13
        )
        heights = view.get(
            "row_heights"
        )  # the normal reviewer keeps its own row-height formula (`crs_export.row_height`)
        ws.row_dimensions[r].height = (
            heights[n - 1] if heights else min(MAX_ROW_HEIGHT, max(15, height))
        )
    style_table(
        ws,
        header_row,
        ncols,
        header_row + len(rows),
        view.get("widths") or LAYOUT_WIDTHS[:ncols],
    )
    _below(ws, view.get("below") or [], header_row + len(rows), ncols)

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
    return wb


def build_layout_crs(view: dict) -> bytes:
    """`layout_workbook` as bytes."""
    buffer = BytesIO()
    layout_workbook(view).save(buffer)
    return buffer.getvalue()
