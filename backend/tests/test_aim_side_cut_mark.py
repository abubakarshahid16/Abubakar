"""The owner's completeness rule on a side-claim cut (update 6): "No text is ever cut without a visible mark and the full text
beside it", and no process words in a comment's text. The comment stays clean; the team file's Comments sheet row carries the
mark and the full text in its "Team note (AI process)" cell, and so does the card; the contractor copy keeps the edited
comment only. Invented words only."""

from __future__ import annotations

from app import (
    aim_review_card,
    aim_review_contractor,
    aim_review_sheet,
    aim_review_view,
)
from app.aim_review import answered as A
from app.aim_review_gate import AI_MARK
from tests.test_g_asks import point

FULL = "The test is set to NO for a pressure part. The team record is not named. State the test."


def _cut_point():
    d = {"comment": FULL, "code": "", "ask": "concern", "label": "Question"}
    answer = {"n": 1, "page": 2, "quote": "the team record is named here", "claim": "record named", "main": False,
              "comment_words": "The team record is not named."}  # fmt: skip
    assert A._outcome(answer, d) == "cut"
    p = point(1, comment=d["comment"], ask="concern")
    p.update(
        aim_review_view.line_view(
            {**p, "code_note": d["code"], "numbers_json": None}, 1
        )
    )
    return p


def test_a_cut_rows_team_note_on_the_comments_sheet_has_the_mark_and_the_full_text():
    p = _cut_point()
    comments, _ = aim_review_view.comments_and_confirmations([p])
    card = aim_review_card.card(comments[0], [p])
    assert card["cut"] == [{"page": 2, "before": FULL}]
    assert (
        card["we_ask"] == "The test is set to NO for a pressure part. State the test."
    )
    model = {
        "comments": [{**comments[0], **card, "decision": None}],
        "mark": AI_MARK,
        "confirmations": [],
    }
    row = aim_review_sheet.comment_rows(model)[0]
    note = row[aim_review_sheet.COMMENT_HEADERS.index("Team note (AI process)")]
    assert (
        "A part the paper answers (page 2) was taken out of this comment." in note
        and f'Full text before: "{FULL}"' in note
    )
    assert "taken out" not in row[aim_review_sheet.COMMENT_HEADERS.index("We ask")]


def test_the_contractor_copy_keeps_only_the_edited_comment():
    p = _cut_point()
    comments, _ = aim_review_view.comments_and_confirmations([p])
    c = {
        **comments[0],
        **aim_review_card.card(comments[0], [p]),
        "decision": {"state": "accept", "text": None},
    }
    row = aim_review_contractor._row(c, 1)
    text = " ".join(
        str(x) for x in (row.values() if isinstance(row, dict) else row) if x
    )
    assert (
        "State the test." in text
        and "The team record is not named." not in text
        and "taken out" not in text
    )
    assert aim_review_contractor._problems("comment", c, row) == []


def test_a_line_with_no_cut_has_no_cut_mark():
    p = point(1, comment="State the value.", ask="concern")
    comments, _ = aim_review_view.comments_and_confirmations([p])
    assert aim_review_card.card(comments[0], [p])["cut"] == []
