"""The two readers' words never enter a comment's text (order 14, after the live sign-off was refused for them): the comment is the first
reader's plain ask; "the readers differ" and each label go in a tag on the card and in the team file only. Invented words only."""

from __future__ import annotations

from openpyxl import load_workbook

from app import (
    aim_review,
    aim_review_card,
    aim_review_contractor,
    aim_review_sheet,
    aim_review_view,
)
from app.aim_review import second_read
from tests.test_g_asks import point

OLD = (
    "To be checked: the two readers differ. First reader (AI opinion): No editions are given. State the editions. "
    "Second reader (Met): Design standards are stated and consistent."
)


def test_a_new_disagreement_keeps_the_first_readers_plain_words_and_puts_both_readers_in_the_note():
    d = {
        "label": "Not met",
        "comment": "State the editions.",
        "code": "",
        "page": 1,
        "quote": "q",
    }

    class Paper:
        pages = {1: "unrelated"}

    second_read._apply(
        {"reads": [{"n": 1, "label": "Met", "quote": "", "reason": "Stated; fine."}]},
        {1: d},
        Paper(),
    )
    assert d["comment"] == "State the editions." and d["label"] == "Question"
    assert (
        d["code"]
        == f"{aim_review.READERS_DIFFER}: first Not met, second Met: Stated; fine.".replace(
            ";", ",", 1
        )
        or "readers differ" in d["code"]
    )
    assert "reader" not in d["comment"].lower().replace("state the editions.", "")


def test_an_older_runs_framed_comment_is_read_back_as_the_plain_ask_plus_the_tag():
    text, tag = aim_review_card.split_readers(OLD, "")
    assert text == "No editions are given. State the editions."
    assert tag == {
        "first": "AI opinion",
        "second": "Met",
        "reason": "Design standards are stated and consistent.",
    }


def test_a_cut_old_frame_still_loses_the_framing():
    text, tag = aim_review_card.split_readers(
        "To be checked: the two readers differ. First reader (Not met): State the value. Second reader (Que",
        "",
    )
    assert text.startswith("State the value.") and "readers differ" not in text
    assert tag and tag["first"] == "Not met"


def test_a_plain_comment_and_a_hidden_viewer_get_no_labels():
    assert aim_review_card.split_readers("State the value.", "") == (
        "State the value.",
        None,
    )
    row = {"comment": "State it.", "code_note": "readers differ: first AI opinion, second Met: book words", "page": 1,
           "label": "Question", "shown_label": "Question", "book_document_id": "b"}  # fmt: skip
    seen = aim_review_view.line_view(row, 1, hidden=True)
    assert seen["readers"] == {
        "first": "",
        "second": "",
        "reason": "",
    } and "book words" not in str(seen)
    full = aim_review_view.line_view(row, 1, hidden=False)
    assert full["readers"] == {
        "first": "AI opinion",
        "second": "Met",
        "reason": "book words",
    }


def test_the_card_carries_the_tag_the_team_file_a_readers_cell_and_the_contractor_copy_neither():
    p = point(1, comment=OLD, ask="concern")
    p.update(
        aim_review_view.line_view({**p, "code_note": "", "numbers_json": None}, 1)
    )  # as the page builds a point
    comments, _ = aim_review_view.comments_and_confirmations([p])
    card = aim_review_card.card(comments[0], [p])
    assert (
        card["we_ask"] == "No editions are given. State the editions."
        and card["readers"]["second"] == "Met"
    )
    model = {
        "comments": [{**comments[0], **card, "decision": None}],
        "mark": aim_review_gate_mark(),
        "confirmations": [],
    }
    row = aim_review_sheet.comment_rows(model)[0]
    assert (
        "Two readers differ. First reader: AI opinion. Second reader: Met"
        in row[aim_review_sheet.COMMENT_HEADERS.index("Readers")]
    )
    assert "readers differ" not in row[aim_review_sheet.COMMENT_HEADERS.index("We ask")]
    assert (
        "Readers" not in aim_review_contractor.HEADERS
    )  # the contractor copy has no such column


def test_the_contractor_scan_no_longer_refuses_a_readers_differ_comment_of_an_older_run():
    p = point(1, comment=OLD, ask="concern")
    p.update(aim_review_view.line_view({**p, "code_note": "", "numbers_json": None}, 1))
    comments, _ = aim_review_view.comments_and_confirmations([p])
    c = {
        **comments[0],
        **aim_review_card.card(comments[0], [p]),
        "decision": {"state": "accept", "text": None},
    }
    row = aim_review_contractor._row(c, 1)
    assert aim_review_contractor._problems("comment", c, row) == []


def aim_review_gate_mark() -> str:
    from app.aim_review_gate import AI_MARK

    return AI_MARK


def test_a_cards_we_ask_never_carries_the_paired_values_process_note_but_the_comment_keeps_it():
    from app.aim_review import steps

    said = f"The stated 12 bar is above the 10 bar stated on page 3{steps.PAIRED_NOTE}; contractor to confirm the value."
    p = point(1, comment=said, ask="concern")
    comments, _ = aim_review_view.comments_and_confirmations([p])
    card = aim_review_card.card(comments[0], [p])
    assert "AI paired" not in card["we_ask"] and card["we_ask"].endswith(
        "contractor to confirm the value."
    )
    assert (
        "AI paired" in comments[0]["comment"]
    )  # the stored words stay whole (the team file's Comment cell)
