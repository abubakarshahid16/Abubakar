"""LP2 (order 14 live proof, 17 Nov 2026): a general review's line on a CRS row says WHAT to check, never only "Engineer to check
the item.": the paper's point, its page (or "page not recorded") and the reason it rests on (the AI reviewer's own words, labelled as
its words, or the review's own reason). Built through the real files: the AI run's file (`crs_ai_workbook.layout_view` drawn by
`crs_layout.build_layout_crs`, read back) and the paper's one CRS rows (`review_points.ai_point` -> `crs_one.comment_cells`).
Invented values only."""

from __future__ import annotations

import io

import openpyxl

from app import agent_general_crs as question
from app import agent_general_review as core
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_comments, crs_layout, crs_one
from app import review_points as rp
from app.crs_completeness import _table_rows

BARE = "Engineer to check the item."
META = {"paper": "Paper Z", "run_id": "run-lp2", "date": "2026-11-17"}
AI_TEXT = "The isolation step names a valve tag that the valve list does not hold"
CODE_TEXT = core.NO_CHECKLIST


def stored(part: int, cls: str, n: int, text: str, *, model: bool, **kw) -> dict:
    """A general line as `agent_general_job.store_lines` keeps it (`"general": true`), read as every CRS reads it."""
    line = core.finalize_line(
        {"part": part, "verdict_class": cls, "document": "doc-z", "text": text, **kw}
    )
    line.update(general=True, line_id=f"G-{n:03d}", item_id=f"G-{n:03d}", part_word=core.PART_WORDS[part],
                text_source=core.TEXT_FROM_MODEL if model else None)  # fmt: skip
    return line


def lines() -> list[dict]:
    return words.read_now(
        [
            stored(
                5,
                core.CLASS_NOTE,
                1,
                AI_TEXT,
                model=True,
                subkind=core.SUB_ENGINEERING,
                quotes_verified_by_code=True,
                quote_a={
                    "document": "doc-z",
                    "page": 4,
                    "text": "Close valve XV-901 before the test",
                },
            ),
            stored(2, core.CLASS_NOT_REVIEWED, 2, CODE_TEXT, model=False, subkind=None),
            stored(
                2,
                core.CLASS_QUERY,
                3,
                "checklist: test interval: not found in the paper",
                model=True,
                subkind=core.SUB_CHECKLIST,
                topic="test interval",
            ),
            stored(
                1,
                core.CLASS_NOT_CHECKED,
                4,
                "not checked against STD-77, rule book not held",
                model=False,
                subkind=None,
                rule_book="STD-77",
            ),
        ],
        [],
    )


def run_file_comments(given: list[dict]) -> list[str]:
    data = crs_layout.build_layout_crs(WB.layout_view(given, META, "internal"))
    ws = openpyxl.load_workbook(io.BytesIO(data))[crs_layout.LAYOUT_MAIN_SHEET]
    return [
        " ".join(str(c) for c in r if c is not None) for r in _table_rows(ws, "Item No")
    ]


def test_every_general_row_of_the_run_file_names_its_point_page_and_reason():
    rows = run_file_comments(lines())
    assert len(rows) == 4
    assert not any(BARE in r for r in rows)
    note = next(r for r in rows if "engineering comment" in r)
    assert (
        "Engineer to check the paper's point (engineering comment), page 4: the AI reviewer's words, not proven by code: \""
        + AI_TEXT
        + '".'
        in note
    )
    assert (
        '"Close valve XV-901 before the test", page 4' in note
    )  # the quote code verified, with its page
    assert (
        "Contractor to confirm compliance with the rule" not in note
    )  # an engineer's question asks no contractor
    unread = next(r for r in rows if CODE_TEXT in r)
    assert f"page not recorded: the review's own reason: {CODE_TEXT}." in unread
    assert (
        "the AI reviewer's words" not in unread
    )  # code's own words are never labelled as the AI's
    checklist = next(r for r in rows if "test interval" in r)
    assert (
        'Engineer to check the checklist point "test interval", page not recorded'
        in checklist
    )
    assert not any(
        "AI reviewer's words" in r for r in rows if "STD-77" in r or CODE_TEXT in r
    )
    book = next(r for r in rows if "STD-77" in r)
    assert "Engineer to check the paper against STD-77" in book
    assert "No rule book was checked for this point (named: STD-77)." in book


CTX = {"run_id": "r", "paper_document_id": "doc-z", "book_of": {}, "readable": frozenset(), "library": [], "everything": True,
       "documents": frozenset()}  # fmt: skip


def test_the_page_crs_row_takes_the_same_question_and_the_verified_quote():
    line = lines()[0]
    point = rp.ai_point(dict(line), CTX)
    assert point["action"] == question.question_row(line).action
    assert point["paper_quote"] == "Close valve XV-901 before the test"
    assert point["page"] == 4
    c = crs_comments.group([{**point, "id": "a1"}])[0]
    cells, _cut = crs_one.comment_cells(c, {"a1": {**point, "id": "a1"}})
    text = " ".join(str(x) for x in cells if x is not None)
    assert BARE not in text
    assert f'the AI reviewer\'s words, not proven by code: "{AI_TEXT}"' in text
    assert (
        '"Close valve XV-901 before the test" (Checked by code: found on the page.)'
        in text
    )


def test_a_viewer_who_may_not_read_a_named_book_gets_no_free_words_and_no_name():
    line = {**lines()[3], "text": "the paper cites STD-9 for the test, which we hold"}
    hidden_ctx = {
        **CTX,
        "everything": False,
        "library": [{"id": "doc-std9", "document_number": "STD-9"}],
    }
    point = rp.ai_point(dict(line), hidden_ctx)
    assert "STD-9" not in point["action"] and "STD-77" not in point["action"]
    assert (
        question.HIDDEN in point["action"] and question.UNNAMED_BOOKS in point["action"]
    )
    shown = rp.ai_point(dict(line), {**hidden_ctx, "readable": frozenset({"doc-std9"})})
    assert "STD-9" in shown["action"]  # he may read the book: the words are his to see


def test_a_line_that_is_not_a_general_review_line_keeps_the_rule_review_wording():
    rule = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Query",
        "field": "Set pressure",
        "standard": "STD-1",
    }
    assert question.question_row(rule) is None
    assert (
        question.question_row({**rule, "general": "yes"}) is None
    )  # only the stored flag itself


def test_a_line_code_wrote_is_never_labelled_as_the_ai_reviewers_words():
    # the review's own "not reviewed" sentence of a part whose text source is the reader's: code wrote it, so it is the review's reason
    line = stored(
        4,
        core.CLASS_NOT_REVIEWED,
        9,
        f"not reviewed: {core.NO_PROJECT_PAPER}",
        model=True,
        subkind=None,
    )
    action = question.question_row(line).action
    assert "the AI reviewer's words" not in action
    assert (
        f"page not recorded: the review's own reason: not reviewed: {core.NO_PROJECT_PAPER}."
        in action
    )
