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


def renumber(rows: list[dict]) -> list[dict]:
    """Item numbers 1..N on one sheet, no gaps; a permanent number (`crs_ref`) is kept as it is."""
    return [
        r if r.get("crs_ref") else {**r, "item_no": n}
        for n, r in enumerate(rows, start=1)
    ]


def row_values(view: dict, entry: dict) -> list:
    """The cells of one row, in the internal CRS sheet's own column order (`crs_export.build_crs`)."""
    from . import crs_export_quality as quality

    values = [
        entry["item_no"],
        entry["document_name"],
        entry["page_section"],
        entry["comment"],
        entry["comment_by"],
        entry["contractor_response"],
        entry["final_resolution"],
        entry["standard_reference"],
        entry.get("priority_label", ""),
        entry["ai_review_comment"],
        entry["reasoning"],
        entry.get("rule_trust", ""),
    ]
    values[9:] = quality.tail_cells(view, entry, values[9:])
    return values


def write_sheet(wb, view: dict, ticks: list[dict]) -> None:
    """The internal-only sheet, right after the CRS sheet: the title, the count, then the CRS table's own
    columns, one line per tick row."""
    from openpyxl.styles import Alignment, Font

    from . import crs_export as ce

    ws = wb.create_sheet(SHEET, 1)
    ce._write(ws, 1, 1, TITLE).font = Font(name=ce.ARIAL, bold=True, size=12)
    ce._write(ws, 2, 1, COUNT_LINE.format(n=len(ticks))).font = Font(
        name=ce.ARIAL, size=10
    )
    for col, width in ce.WIDTHS.items():
        ws.column_dimensions[col].width = width
    for col, header in enumerate(view["columns"], start=1):
        cell = ce._write(ws, HEADER_ROW, col, header)
        cell.font = Font(name=ce.ARIAL, bold=True, size=10)
        cell.border = ce.BOX
    fill = ce.ROW_FILLS[ce.ROW_KIND_SAFETY_TICK]
    for position, entry in enumerate(ticks, start=1):
        for i, value in enumerate(row_values(view, entry), start=1):
            cell = ce._write(ws, HEADER_ROW + position, i, value)
            cell.font = Font(name=ce.ARIAL, size=10)
            cell.alignment = Alignment(
                horizontal="left", vertical="top", wrap_text=True
            )
            cell.border, cell.fill = ce.BOX, fill
