"""Tests for the CRS generator. Standalone: no db, no app fixtures.

Written and first run by Cowork against the client's real template shape;
9 tests. The structural assertions (headers, merges) ARE the spec - they
were measured from CRS - Form of Agreement_2028 1.xlsx, not invented.
"""
import io

import openpyxl

from app.crs_export import HEADERS, build_crs

META = {"project": "DORRA", "document_title": "Doc T",
        "date_issued": "2026-09-19"}


def load(findings, meta=META):
    return openpyxl.load_workbook(io.BytesIO(build_crs(findings, meta))).active


def test_headers_match_the_client_template_exactly():
    ws = load([])
    assert [ws.cell(row=8, column=c).value for c in range(1, 8)] == HEADERS


def test_the_contractor_columns_are_always_empty():
    ws = load([{"document_name": "d", "page_section": "p",
                "comment": "c", "comment_by": "b"}])
    assert ws.cell(row=9, column=6).value in (None, "")
    assert ws.cell(row=9, column=7).value in (None, "")


def test_item_numbers_are_assigned_1_to_n_with_no_gaps():
    ws = load([{"comment": f"c{i}"} for i in range(5)])
    assert [ws.cell(row=8 + n, column=1).value
            for n in (1, 2, 3, 4, 5)] == [1, 2, 3, 4, 5]


def test_the_header_block_carries_the_meta():
    ws = load([], {"project": "DFDP", "document_title": "Sour Water Drums",
                   "company_transmittal": "KJO-TX-001",
                   "date_issued": "2026-09-19"})
    assert "DFDP" in ws.cell(row=1, column=1).value
    assert ws.cell(row=2, column=1).value == "COMMENT RESOLUTION SHEET"
    assert ws.cell(row=3, column=3).value == "KJO-TX-001"
    assert ws.cell(row=5, column=3).value == "Sour Water Drums"


def test_missing_meta_renders_as_nothing_never_none_text():
    ws = load([], {"project": "X"})
    for row in (3, 4, 6, 7):
        value = ws.cell(row=row, column=3).value
        assert value in (None, ""), f"row {row} leaked {value!r}"


def test_empty_findings_yield_a_valid_sheet_with_no_data_rows():
    ws = load([])
    assert ws.cell(row=9, column=1).value is None


def test_merges_match_the_template_shape():
    ws = load([])
    merges = {str(r) for r in ws.merged_cells.ranges}
    for merge in ("A1:G1", "A2:G2", "A3:B3", "C3:G3", "A7:B7", "C7:G7"):
        assert merge in merges


def test_a_long_comment_gets_a_taller_row():
    short = load([{"comment": "short"}]).row_dimensions[9].height
    long_ = load([{"comment": "x" * 400}]).row_dimensions[9].height
    assert long_ > short


def test_every_data_cell_is_bordered():
    ws = load([{"comment": "c"}])
    for col in range(1, 8):
        assert ws.cell(row=9, column=col).border.top.style == "thin"
