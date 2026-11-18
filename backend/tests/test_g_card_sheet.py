# ruff: noqa: F811
"""The Comments sheet in the card layout (planner 19:00, owner: 'not easy to read'): Severity, Title, Paper says, Rule says, We ask, Applies to
first; the technical columns kept but hidden; the mark in the Status cell; the severity counts on the Summary. Invented papers only."""

from __future__ import annotations

import pytest

from app import aim_review_card as CARD
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


def _rows(ws):
    return [
        r
        for r in ws.iter_rows(min_row=S.HEADER_ROW + 1, values_only=True)
        if r[0] is not None
    ]


def test_the_comments_sheet_leads_with_the_card_columns():
    assert S.COMMENT_HEADERS[:7] == (
        "No.",
        "Severity",
        "Title",
        "Paper says",
        "Rule says",
        "We ask",
        "Applies to",
    )
    assert (
        S.COMMENT_HEADERS[0] == S.FIRST_HEADER
        and "Status" in S.COMMENT_HEADERS
        and "Lines" in S.COMMENT_HEADERS
    )


def test_each_comment_row_is_a_card(workbook):
    ws = workbook[S.COMMENTS]
    at = {h: i for i, h in enumerate(S.COMMENT_HEADERS)}
    rows = _rows(ws)
    assert rows
    for r in rows:
        assert (
            r[at["Severity"]] in CARD.SEVERITIES[:3]
        )  # a comment is never "Please confirm" (its own sheet)
        assert r[at["Title"]] and len(str(r[at["Title"]]).split()) <= CARD.TITLE_WORDS
        assert r[at["We ask"]] and r[at["Paper says"]]
        assert r[
            at["Applies to"]
        ]  # one line per place: "p4 · field", or the field alone when the place has no page (never "p0")
        assert (
            r[at["Status"]] == "AI, to be checked"
            and r[at["Engineer decision"]] is None
        )


def test_the_severity_cell_is_coloured_by_its_word(workbook):
    ws = workbook[S.COMMENTS]
    col = S.COMMENT_HEADERS.index("Severity") + 1
    for r in range(S.HEADER_ROW + 1, S.HEADER_ROW + 1 + len(_rows(ws))):
        cell = ws.cell(row=r, column=col)
        assert cell.fill.fgColor.rgb.endswith(S.SEVERITY_FILLS[cell.value])


def test_the_technical_columns_are_kept_but_hidden_and_the_card_columns_are_shown(
    workbook,
):
    ws = workbook[S.COMMENTS]
    from openpyxl.utils import get_column_letter

    hidden = {
        h
        for i, h in enumerate(S.COMMENT_HEADERS, 1)
        if ws.column_dimensions[get_column_letter(i)].hidden
    }
    assert hidden == set(S.HIDDEN_COLUMNS)
    for shown in (
        "Severity",
        "Title",
        "Paper says",
        "Rule says",
        "We ask",
        "Applies to",
        "Page",
        "Status",
        "Engineer decision",
    ):
        assert shown not in hidden


def test_the_file_still_passes_its_own_completeness_read_back(workbook):
    # the download answered 200: the Lines cells (hidden) and the Status marks (read by header) were read back and agree
    assert workbook[S.COMMENTS]["A1"].value == "AI, to be checked"


def test_the_summary_says_the_comments_by_severity(workbook):
    text = "\n".join(
        str(c) for r in workbook[S.SUMMARY].iter_rows(values_only=True) for c in r if c
    )
    assert "Comments by severity" in text and "Check a value" in text
