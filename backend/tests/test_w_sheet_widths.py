# ruff: noqa: F811
"""The general review's Excel: column widths are set by HEADER NAME and every table has a filter on its header row.

Seen on the live valve file: the widths were listed by position, a header had moved, and every width sat one column off (Field 7 wide,
so its text broke one word per line; Shown label 70). Invented papers only."""

from __future__ import annotations

import pytest
from openpyxl.utils import get_column_letter

from app import aim_review_sheet as S
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, _sheet, client, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture
def workbook(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run()
    return _sheet(
        client(PAPER, BOOK).get(
            f"/api/reviews/papers/{PAPER}/general/sheet?run_id={RUN}"
        )
    )


TABLES = [
    (S.COMMENTS, S.COMMENT_HEADERS),
    (S.CONFIRMATIONS, S.COMMENT_HEADERS),
    (S.ALL_POINTS, S.POINT_HEADERS),
]


def _by_header(ws) -> dict[str, float]:
    return {
        str(c.value): ws.column_dimensions[get_column_letter(c.column)].width
        for c in ws[S.HEADER_ROW]
        if c.value
    }


@pytest.mark.parametrize(("sheet", "headers"), TABLES)
def test_every_column_has_the_width_its_header_names(workbook, sheet, headers):
    got = _by_header(workbook[sheet])
    assert list(got) == list(headers)
    for name, width in got.items():
        assert width == S.COLUMN_WIDTHS.get(name, S.DEFAULT_WIDTH), name


@pytest.mark.parametrize(("sheet", "headers"), TABLES)
def test_the_text_columns_are_wide_and_the_bookkeeping_columns_narrow(
    workbook, sheet, headers
):
    got = _by_header(workbook[sheet])
    assert (
        got["Field"] >= 20 and got["Shown label"] >= 14 and got["Comment"] >= 50
    )  # read, not one word per line
    for narrow in ("Lines", "Item", "Note", "No.", "Page"):
        if narrow in got:
            assert got[narrow] <= 16, narrow


@pytest.mark.parametrize(("sheet", "headers"), TABLES)
def test_the_header_row_has_a_filter_over_the_whole_table(workbook, sheet, headers):
    ws = workbook[sheet]
    first, last = ws.auto_filter.ref.split(":")
    assert first == f"A{S.HEADER_ROW}"
    assert last.startswith(get_column_letter(len(headers)))
    assert int(last[len(get_column_letter(len(headers))) :]) >= S.HEADER_ROW + 1


def test_a_header_that_moves_keeps_its_width(workbook):
    """The point of the fix: the widths follow the NAMES. A column order the writer did not expect still gets each name's width."""
    from openpyxl import Workbook

    ws = Workbook().active
    headers = ("Comment", "Field", "No.", "Shown label")
    S._table(ws, headers, [["c", "f", 1, "q"]])
    assert [ws.column_dimensions[get_column_letter(i)].width for i in range(1, 5)] == [
        S.COLUMN_WIDTHS["Comment"], S.COLUMN_WIDTHS["Field"], S.COLUMN_WIDTHS["No."], S.COLUMN_WIDTHS["Shown label"],
    ]  # fmt: skip
