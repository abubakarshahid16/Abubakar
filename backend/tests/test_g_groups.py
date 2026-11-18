"""The editor's (S5) groups are applied by code, losslessly and per kind (lead 3, 18 Nov 2026). Invented words only. No model, no call."""

from __future__ import annotations

from app import aim_review_view
from app.aim_review import editor, prompts
from tests.test_g_asks import point


def grouped(*lines: dict, mark: int | None = None) -> list[dict]:
    """Lines marked as one editor group: `same_point_as` is the group's first line number (as `aim_review_view.line_view` reads it)."""
    for p in lines:
        p["same_point_as"] = mark if mark is not None else lines[0]["n"]
    return list(lines)


def test_the_editor_s_group_becomes_one_comment_keeping_every_rule_page_and_word():
    pts = grouped(
        point(
            1,
            field="Value A vs B",
            page=4,
            standard="BOOK-1",
            clause="3.1",
            comment="A is below B (rule one).",
        ),
        point(
            2,
            field="Limit of A",
            page=5,
            standard="BOOK-2",
            clause="9.9",
            comment="A must exceed B (rule two).",
        ),
        point(
            3,
            field="A and B",
            page=6,
            standard="BOOK-3",
            clause="2.2",
            comment="State A against B (rule three).",
        ),
    )
    comments, confirmations = aim_review_view.comments_and_confirmations(pts)
    assert [c["lines"] for c in comments] == [[1, 2, 3]] and confirmations == []
    one = comments[0]
    assert one["pages"] == [4, 5, 6]  # every page
    for words in (
        "rule one",
        "rule two",
        "rule three",
        "BOOK-1",
        "BOOK-2",
        "BOOK-3",
        "3.1",
        "9.9",
        "2.2",
    ):
        assert (
            words in one["comment"]
            or words in one["standard"]
            or words in one["clause"]
        ), words  # every rule's own words
    assert (
        "Value A vs B" in one["field"]
        and "Limit of A" in one["field"]
        and "A and B" in one["field"]
    )


def test_a_group_never_merges_a_firm_finding_with_a_question_or_two_compare_kinds():
    pts = [
        point(1, label="Not met", shown_label="Fail, compared by code"),
        point(2, field="Other field", page=9),
        point(3, field="Third field", page=8, compare_kind="paper"),
    ]
    for p in pts:
        p["same_point_as"] = 1  # the editor (wrongly) put all three in one group
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    assert sorted(c["lines"] for c in comments) == [
        [1],
        [2],
        [3],
    ]  # code re-checks the kind: nothing merged


def test_two_groups_and_an_ungrouped_comment_stay_apart():
    pts = [
        *grouped(point(1, field="F1", page=1), point(2, field="F2", page=2)),
        *grouped(point(3, field="F3", page=3), point(4, field="F4", page=4)),
        point(5, field="F5", page=5),
    ]
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    assert [c["lines"] for c in comments] == [[1, 2], [3, 4], [5]]


def test_the_group_is_the_same_for_every_viewer():
    """A line of a hidden book keeps its group: the mark is read from the STORED note, not from what the viewer may see."""
    stored = {"code_note": "same point as line 7; edited: x"}
    assert aim_review_view._group_of(stored["code_note"]) == 7
    row = {
        "code_note": stored["code_note"],
        "page": 1,
        "label": "Question",
        "shown_label": "Question",
    }
    assert aim_review_view.line_view(row, 1, hidden=True)["same_point_as"] == 7
    assert aim_review_view.line_view(row, 1, hidden=False)["same_point_as"] == 7
    assert aim_review_view._group_of("provisional") is None


def test_the_editor_is_asked_for_groups_with_the_rule_of_each_comment():
    assert (
        "GROUPING IS YOUR MAIN JOB" in prompts.EDIT_TASK
        and "rule, comment, quote" in prompts.EDIT_TASK
    )
    lines = {
        1: {
            "field": "F",
            "page": 1,
            "standard": "BOOK-1",
            "clause": "3.1",
            "comment": "c",
            "quote": "q",
        }
    }

    class Spy:
        asked: list = []

        def ask(self, **kw):
            Spy.asked.append(kw["prompt"])
            return {"moves": [], "groups": []}

    from app.aim_review.paper import Paper

    editor._ask(
        Spy(), Paper(paper_id="doc_edit", pages={1: "Invented page."}), lines, "lead"
    )
    assert '"rule": "BOOK-1 3.1"' in Spy.asked[0]


def test_in_a_merged_group_the_concern_comes_first_and_an_approving_member_after():
    pts = grouped(
        point(
            1, field="F1", page=1, comment="The rating is acceptable.", ask="concern"
        ),
        point(
            2,
            field="F2",
            page=2,
            comment="The value is blank, state it.",
            ask="concern",
        ),
        point(
            3, field="F3", page=3, comment="The value is blank here too.", ask="concern"
        ),
    )
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    one = comments[0]
    assert (
        one["lines"] == [1, 2, 3] and one["n"] == 1
    )  # the comment keeps its place on the sheet
    assert one["comment"].startswith("The value is blank, state it.")  # a concern leads
    assert one["comment"].index("blank here too") < one["comment"].index(
        "acceptable"
    )  # the approving member is last
    assert one["pages"] == [1, 2, 3]  # nothing is dropped
