"""Owner order 11 Nov 2026 (step 1, #805), behind CRS_ROUTING_BY_HOLD_REASON_ENABLED (off): the safety-tick
rows (a tested rule passed a safety field; the engineer ticks it, `rule_trust.label_check`) are not CRS
comments. On the internal copy they print on their own sheet, never on the CRS sheet; the issue copy never
carries them (`crs_export.build_crs_view`, as before). Which rows leave is decided in `crs_export._tick_section`;
this module only draws the sheet. Nothing here changes a verdict, a row's words or a count.

Excel allows no ":" in a sheet name and at most 31 characters, so the sheet is named by the title's first part
and its first line is the title in full.
"""

from __future__ import annotations

TITLE = "Passed by a tested rule: engineer to tick"
SHEET = "Passed by a tested rule"
COUNT_LINE = (
    "{n} rows of this review run where a tested rule passed a safety field. They are not CRS comments"
    " and are never on the contractor copy: read the clause and the value on the page, then tick"
    " each one or say what is off."
)
#: The column header row: the title, the count line, one blank row, then the header.
HEADER_ROW = 4


def row_values(view: dict, entry: dict) -> list:  # noqa: ARG001 - kept for the callers' signature
    """The cells of one row, in the one layout's column order (`crs_normal.row_cells`)."""
    from . import crs_normal

    return crs_normal.row_cells(entry)[0]


def write_sheet(wb, view: dict, ticks: list[dict]) -> None:
    """The internal-only sheet, right after the CRS sheet: the title, the count, then the CRS table's own
    columns, one line per tick row."""
    from openpyxl.styles import Font

    from . import crs_export as ce

    ws = wb.create_sheet(SHEET, 1)
    ce._write(ws, 1, 1, TITLE).font = Font(name=ce.ARIAL, bold=True, size=12)
    ce._write(ws, 2, 1, COUNT_LINE.format(n=len(ticks))).font = Font(
        name=ce.ARIAL, size=10
    )
    from . import crs_layout

    for col, header in enumerate(crs_layout.LAYOUT_COLUMNS, start=1):
        ce._write(ws, HEADER_ROW, col, header)
    for position, entry in enumerate(ticks, start=1):
        for i, value in enumerate(row_values(view, entry), start=1):
            ce._write(ws, HEADER_ROW + position, i, value)
        for i in range(1, len(crs_layout.LAYOUT_COLUMNS) + 1):
            ws.cell(HEADER_ROW + position, i).fill = crs_layout.STATUS_FILLS["Pass"]
    crs_layout.style_table(
        ws,
        HEADER_ROW,
        len(crs_layout.LAYOUT_COLUMNS),
        HEADER_ROW + len(ticks),
        crs_layout.LAYOUT_WIDTHS,
    )
