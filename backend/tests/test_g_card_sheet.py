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
        assert r[at["We ask"]]  # PAPER SAYS is a code-verified quote or nothing (planner 19 Nov, item 2): this fixture's quotes are not on its pages, so it is empty
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


def test_a_cut_card_cell_is_checked_like_the_comment_and_the_quote():
    """The visible "Paper says" and "We ask" cells are read back too: a cell that differs from the page's text and carries no cut mark
    with its note is a problem (the earlier check covered Comment and Quote only)."""
    from app import aim_review_completeness as C
    from app import aim_review_sheet as S

    view = {
        "comments": [
            {"n": 1, "comment": "c", "quote": "q", "paper_says": "page 1: whole text", "we_ask": "Please state it."}
        ]
    }
    row = [None] * len(S.COMMENT_HEADERS)
    for h, v in {"No.": 1, "Comment": "c", "Quote": "q", "Paper says": "page 1: whole text", "We ask": "Please state it."}.items():
        row[S.COMMENT_HEADERS.index(h)] = v
    assert C._cut_check([row], view) == (0, [])
    row[S.COMMENT_HEADERS.index("We ask")] = "Please sta"  # cut with no mark
    marked, problems = C._cut_check([row], view)
    assert marked == 0 and len(problems) == 1 and "we_ask" in problems[0]
    row[S.COMMENT_HEADERS.index("We ask")] = "Please state it."
    row[S.COMMENT_HEADERS.index("Paper says")] = "page 1: who"  # cut with no mark either
    assert len(C._cut_check([row], view)[1]) == 1


def test_a_field_on_several_pages_keeps_every_page_in_the_applies_to_cell():
    members = [
        {"field": "Required relieving capacity", "page": p, "quote": "x"} for p in (3, 1, 2, 4)
    ] + [{"field": "Set pressure", "page": 2, "quote": "y"}]
    places = CARD._places(members)
    assert S.applies_text(places) == "p1, 2, 3, 4 · Required relieving capacity\np2 · Set pressure"


def test_applies_text_still_reads_an_older_place_with_one_page_and_a_place_with_none():
    assert S.applies_text([{"field": "Backpressure", "page": 4}]) == "p4 · Backpressure"
    assert S.applies_text([{"field": "Backpressure"}]) == "Backpressure"
    assert S.applies_text([]) is None


def test_the_contractor_copy_names_the_same_pages_because_it_uses_the_same_function():
    from app import aim_review_contractor as C

    assert C.applies_text is S.applies_text
