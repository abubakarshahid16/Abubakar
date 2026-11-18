"""A sent comment must ask something (`aim_review.asks`) and the same point under several rules is one comment (`_same_place`) - order 14,
after the v3 strict judges. Invented words only. No model, no call."""

from __future__ import annotations

import pytest

from app import aim_review, aim_review_view
from app.aim_review import asks


def decided(
    comment: str,
    *,
    ask: str = "concern",
    label: str = "Question",
    deferred: bool = False,
    **kw,
) -> dict:
    """One decided item as the engine holds it (before `to_line`)."""
    return {"item_id": "C1", "label": label, "ask": ask, "deferred": deferred, "comment": comment, "field": "Wall", "page": 1,
            "quote": "Wall thickness : 12 mm", "code": "", **kw}  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        "Pressure-part allowance of 3.2 mm is within the 3.2 mm maximum.",
        "Highest design temperature of 149 C is well below the 400 C limit.",
        "External gasket type is stated as spiral wound. Internal gaskets are referenced to Note M18.",
        "The 3.2 mm allowance is at the maximum of 3.2 mm.",
    ],
)
def test_a_confirm_that_states_a_pass_or_a_restatement_asks_nothing(text):
    assert not asks.has_request(text)
    assert asks.asks_nothing(decided(text, ask="confirm"))


@pytest.mark.parametrize(
    "text",
    [
        "The stated set pressure is above the vessel rating.",
        "Material grade here conflicts with the grade on sheet 2.",
        "Design pressure 3.5 bar is below the maximum operating pressure 3.8 bar.",
        "Pressure-part corrosion allowance of 3.2 mm is within the 3.2 mm maximum.",  # even a pass-looking sentence: a concern is the judge's own suspicion
    ],
)
def test_a_concern_is_never_taken_off_for_having_no_request_word(text):
    """A concern states a conflict and needs no request word to be a real find; only the judge's "confirm" can be a no-ask line."""
    assert not asks.has_request(text)
    assert not asks.asks_nothing(decided(text, ask="concern"))
    assert not asks.asks_nothing(
        decided(text)
    )  # the helper's default mark is "concern"


@pytest.mark.parametrize(
    "text",
    [
        "The 10 % overpressure is acceptable. Confirm the valve is liquid capacity-certified.",  # a pass, then a real ask
        "Is the seal plan 53 or 54?",
        "The procedure does not say how changes are authorised.",  # a named gap is a request
        "Blowdown is blank, so reseat cannot be checked.",
        "Design pressure is below operating pressure; the design must cover it.",
        "Vendor to state the static head.",
    ],
)
def test_a_comment_with_any_request_or_named_gap_is_kept(text):
    assert asks.has_request(text)
    assert not asks.asks_nothing(decided(text))


def test_only_a_question_on_a_stated_value_is_judged():
    quiet = "The value is within the limit."
    assert asks.asks_nothing(decided(quiet, ask="confirm"))
    assert not asks.asks_nothing(
        decided(quiet, ask="concern")
    )  # the judge suspects the value: never taken off
    assert not asks.asks_nothing(decided(quiet, ask="open"))  # a blank IS the question
    assert not asks.asks_nothing(decided(quiet, ask="confirm", deferred=True))
    assert not asks.asks_nothing(
        decided(quiet, ask="")
    )  # an older run recorded no mark: never touched
    assert not asks.asks_nothing(
        decided(quiet, label="Not met")
    )  # a code verdict is never a pass statement
    assert not asks.asks_nothing(decided(quiet, label="AI opinion", ask=""))


def test_mark_keeps_the_line_and_says_why_and_it_is_no_longer_sent():
    lines = [
        decided("The thickness is within the limit.", ask="confirm"),
        decided("State the thickness.", ask="confirm"),
        decided(
            "The thickness is above the rating.", ask="concern"
        ),  # a concern is never marked
    ]
    from app.aim_review.engine import to_line

    assert [aim_review.sendable(to_line(n, d)) for n, d in enumerate(lines, 1)] == [
        True,
        True,
        True,
    ]
    assert asks.mark(lines) == 1
    assert (
        aim_review.NO_ASK in lines[0]["code"]
        and lines[1]["code"] == ""
        and lines[2]["code"] == ""
    )
    assert [aim_review.sendable(to_line(n, d)) for n, d in enumerate(lines, 1)] == [
        False,
        True,
        True,
    ]
    assert asks.mark(lines) == 0  # nothing left to mark: a second pass changes nothing


def test_a_marked_line_is_still_a_point_and_never_a_comment():
    from app.aim_review.engine import to_line

    lines = [decided("The thickness is within the limit.", ask="confirm")]
    asks.mark(lines)
    row = to_line(1, lines[0])
    assert (
        aim_review.NO_ASK in row["code_note"] and row["comment"]
    )  # kept whole on All points
    point = {**row, "n": 1, "shown_label": "Question", "pages": [1], "ask": "confirm", "deferred": False, "numbers": None,
             "code_note": row["code_note"], "quote_unverified": False, "compare_kind": "", "compared": ""}  # fmt: skip
    comments, confirmations = aim_review_view.comments_and_confirmations([point])
    assert comments == [] and confirmations == []


# ---- the same place, sent under several rules, is ONE comment ----------------------------------------------------------------


def point(
    n: int,
    *,
    field="Design pressure",
    page=4,
    label="Question",
    comment=None,
    standard="BOOK-1",
    clause="1",
    item=None,
    **kw,
):
    return {"n": n, "item_id": item or f"C{n}", "finding_no": 1, "label": label, "shown_label": label, "field": field, "page": page,
            "quote": f"{field} : {n} bar", "quote_unverified": False, "comment": comment or f"Please confirm {field} (rule {n}).",
            "standard": standard, "clause": clause, "source": "held standard", "topic": f"topic {n}", "code_note": "", "compared": "",
            "compare_kind": "", "compare_result": "", "ask": "concern", "deferred": False, "numbers": None, "book_document_id": "",
            **kw}  # fmt: skip


def test_two_rules_on_the_same_field_and_page_are_one_comment_listing_both_rules():
    pts = [
        point(1, standard="BOOK-1", clause="3.1"),
        point(2, standard="BOOK-2", clause="9.9"),
        point(3, field="Wall", page=5),
    ]
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    assert [c["lines"] for c in comments] == [
        [1, 2],
        [3],
    ]  # the third is another field: untouched
    merged = comments[0]
    assert (
        "rule 1" in merged["comment"] and "rule 2" in merged["comment"]
    )  # each rule's own words are kept
    assert merged["pages"] == [4]


def test_the_same_field_on_another_page_or_another_label_is_not_merged():
    pts = [
        point(1),
        point(2, page=7),  # another page: another place
        point(3, label="AI opinion"),  # a Question never joins an AI opinion
        point(4, field="Other field"),
    ]
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    assert sorted(c["lines"] for c in comments) == [[1], [2], [3], [4]]


def test_a_failure_is_never_merged_with_another_finding():
    pts = [
        point(1, label="Not met", shown_label="Fail, compared by code"),
        point(2, label="Not met", shown_label="Fail, compared by code"),
    ]
    for p in pts:
        p["compare_kind"] = "paper"
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    assert sorted(c["lines"] for c in comments) == [[1], [2]]


def test_no_chain_a_comment_spanning_two_places_stays_alone():
    pts = [
        point(1),
        point(2, item="C1", page=5),
        point(3, page=5),
    ]  # items C1: lines 1 and 2 are one comment over pages 4 and 5
    comments, _ = aim_review_view.comments_and_confirmations(pts)
    covered = sorted(n for c in comments for n in c["lines"])
    assert covered == [1, 2, 3]  # every sent line is in exactly one comment


@pytest.mark.parametrize(
    "text",
    [
        "The set pressure is well above the design pressure of the vessel.",
        "Operating temperature is well above the rated temperature of the lining.",
        "Material is consistent with sheet 2 while the corrosion allowance is zero for sour service.",
        "Two capacities are stated: 40 and 55; 55 meets the duty.",
        "The stated grade is acceptable for sweet service and this line is in sour service.",
        "Carbon steel is adequate for water, the fluid here being acid.",
        "The rating conforms to the superseded edition of the code.",
    ],
)
def test_a_concern_is_never_held_back_whatever_its_words(text):
    """Review rounds 1 to 3 of 18 Nov: each sentence states a real conflict in words a pass-word list read as a pass. A concern
    is the judge's own suspicion and is always sent; only a "confirm" that asks nothing is held back."""
    assert not asks.asks_nothing(decided(text, ask="concern"))


def test_a_line_that_only_confirms_a_stated_value_leaves_the_sent_comment_of_its_check():
    """Per line, before the lines of one check are grouped (the stored v3 sheets: 44 confirm lines rode inside sent comments)."""
    confirm = point(1, item="C1", page=1, ask="confirm")
    concern = point(
        2, item="C1", page=2, ask="concern", comment="The value is wrong, revise it."
    )
    comments, confirmations = aim_review_view.comments_and_confirmations(
        [confirm, concern]
    )
    assert [c["lines"] for c in comments] == [[2]] and [
        c["lines"] for c in confirmations
    ] == [[1]]
    assert (
        "Please confirm" not in comments[0]["comment"]
    )  # the confirm line's words are on the confirmations sheet, not in the comment
    # an older line with no recorded mark, an unverified quote or a compared figure stays in the comment, as before
    keep = [
        point(3, item="C2", page=1, ask="confirm", quote_unverified="x"),
        point(4, item="C2", page=2, ask="concern"),
    ]
    comments, confirmations = aim_review_view.comments_and_confirmations(keep)
    assert [c["lines"] for c in comments] == [[3, 4]] and confirmations == []


@pytest.mark.parametrize(
    "line",
    [
        {
            "comment": "",
            "ask": "concern",
        },  # update 5: an empty pass with numbers was marked "concern" and sent
        {"comment": "   \n ", "ask": "confirm"},
        {"comment": "", "label": "AI opinion", "ask": ""},
        {"comment": "", "label": "Not met", "ask": ""},
    ],
)
def test_a_line_whose_own_comment_has_no_words_is_never_sent(line):
    """Kept on All points with the not-sent note and why; whatever its label or mark (an empty text is empty, no word list)."""
    from app import aim_review
    from app.aim_review.engine import to_line

    d = decided(
        **{
            "comment": line["comment"],
            "ask": line.get("ask", "concern"),
            "label": line.get("label", "Question"),
        }
    )
    assert asks.mark([d]) == 1 and asks.NO_WORDS_REASON in d["code"]
    assert not aim_review.sendable(to_line(1, d))


def test_a_line_with_words_or_an_open_value_is_not_held_for_having_no_words():
    from app import aim_review
    from app.aim_review.engine import to_line

    for d in (
        decided("The wall is thinner than the minimum."),
        decided("x", ask="open", deferred=True),
    ):
        asks.mark([d])
        assert aim_review.sendable(to_line(1, d))


def test_a_line_with_only_codes_absence_filler_and_nothing_named_is_never_sent():
    """The spec review of 19 Nov: code's own "not on any page" line, with no field, page or quote, asks nothing the contractor can
    act on; it stays on All points. The same words beside a named field, a page or a quote are kept (a real missing value)."""
    from app import aim_review
    from app.aim_review.engine import to_line
    from app.aim_review.steps import NOT_ON_ANY_PAGE_WORDS

    bare = decided(NOT_ON_ANY_PAGE_WORDS, field="", page=None, quote="")
    assert asks.mark([bare]) == 1 and not aim_review.sendable(to_line(1, bare))
    for named in (decided(NOT_ON_ANY_PAGE_WORDS, field="Seal plan", page=None, quote=""),
                  decided(NOT_ON_ANY_PAGE_WORDS, field="", page=2, quote=""),
                  decided("The seal plan is not shown on any page.", field="", page=None, quote="")):  # fmt: skip
        asks.mark([named])
        assert aim_review.sendable(to_line(1, named))
