"""Order 13: the normal reviewer's CRS gets the same header row, frozen panes and print setup as the AI reviewer's (one exporter).
Content, order, numbers and cell styles of the rows are unchanged (the frozen layouts of #1503 and #1738 differ only on the
header row). Invented data only."""

from __future__ import annotations

import io

import openpyxl
import pytest

from app import crs_export, crs_layout


def _book(copy: str):
    rows = [
        {
            "document_name": "DS-1.pdf",
            "page_section": "p.2",
            "comment": "Set pressure is above the limit.",
            "comment_by": "Engineer",
            "row_kind": "non_compliant",
            "engineer_confirmed": True,
            "priority": 1,
            "standard_reference": "STD-1 4.1",
        }
    ]
    data = crs_export.build_crs(
        rows, {"review_run_id": "r", "copy": copy, "export_quality": False}
    )
    return openpyxl.load_workbook(io.BytesIO(data))["CRS"]


@pytest.mark.parametrize("copy", ["internal", "issue"])
def test_the_normal_reviewers_sheet_has_the_shared_header_and_print_setup(copy):
    ws = _book(copy)
    top = crs_export.COLUMN_HEADER_ROW
    assert ws.cell(top, 1).value == "Item No"
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(top, col)
        assert (
            cell.font.bold
            and cell.fill.fgColor.rgb == "FF1F3864"
            and cell.border.left.style == "thin"
        )
    assert ws.freeze_panes == f"A{top + 1}"
    assert (
        ws.page_setup.orientation == "landscape"
        and ws.page_setup.fitToWidth == 1
        and ws.page_setup.fitToHeight == 0
    )
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_title_rows == f"${top}:${top}"
    assert ws.print_area.startswith("'CRS'!$A$1:")


def test_the_normal_reviewers_rows_keep_their_own_fill_and_text():
    ws = _book("internal")
    row = crs_export.FIRST_DATA_ROW
    assert ws.cell(row, 4).value == "Set pressure is above the limit."
    assert (
        ws.cell(row, 1).fill.fgColor.rgb
        == crs_export.ROW_FILLS["non_compliant"].fgColor.rgb
    )  # not the header fill


def test_one_function_styles_both_layouts():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Item No", "Status"])
    ws.append([1, "Fail"])
    crs_layout.style_table(ws, 1, 2, 2, (8.0, 12.0))
    assert ws.freeze_panes == "A2" and ws.column_dimensions["B"].width == 12.0
    assert (
        ws.cell(2, 2).border.top.style == "thin"
        and ws.cell(1, 1).fill.fgColor.rgb == "FF1F3864"
    )
