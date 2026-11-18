"""A limit written AFTER its number ("300 psig or less") is a limit code can compare (order 14, update 5: the new-book test's
"<value> psig or less" rule gave "no comparison code can read", so a filled-in 340 psig was never compared). Invented values only."""

from __future__ import annotations

import pytest

from app import aim_review_store
from app.aim_review import steps as S
from app.aim_review import verify
from app.aim_review.paper import Paper

STATED = "Relief setting 340 psig (By Contractor, to suit the duty)"
PAPER = Paper(
    paper_id="doc_p", pages={1: STATED + "\nInlet size psig (By Contractor)\n"}
)
BOOKS = {"B01": {"alias": "B01", "book": "doc_b", "identifier": "QX-STD-101"}}


def _decide(rule_quote: str, *, rule_value="300", paper_value="340", label="Question"):
    item = {
        "id": "C001",
        "book": "B01",
        "clause": "4.1",
        "source": S.HELD,
        "topic": "t",
        "kind": "limit",
        "rule_quote": rule_quote,
    }
    j = {"label": label, "quote": STATED, "page": 1, "comment": "the model's words",
         "numbers": {"paper_value": paper_value, "paper_unit": "psig", "operator": "", "rule_value": rule_value, "rule_unit": "psig"}}  # fmt: skip
    return S._decide(item, j, PAPER, BOOKS, "")


@pytest.mark.parametrize(
    ("words", "op"),
    [
        ("The stated set pressure shall be 300 psig or less for each valve.", "<="),
        ("Keep it at 300 psig or lower.", "<="),
        ("Keep it at 300 psig and below.", "<="),
        ("Allowed: 300 psig max.", "<="),
        ("Allowed: 300 psig maximum.", "<="),
        ("Hold at least 300 psig or more.", ">="),
        ("Hold 300 psig or greater.", ">="),
        ("Hold 300 psig and above.", ">="),
        ("Hold 300 psig min.", ">="),
        (
            "The set pressure shall not exceed 300 psig.",
            "<=",
        ),  # the words before the number still win
    ],
)
def test_the_operator_after_the_number_is_read_by_code(words, op):
    assert verify.quoted_value("300", words)["op"] == op


@pytest.mark.parametrize(
    "words",
    [
        "The pressure is 300 psig.",
        "Test at 300 psig or less than the rating of the valve.",  # "less than" names no operator after the number
        "Test at 300 psig or lessen it.",
        "Check 300 psig or more often.",
        "The maximum is not 300 psig here or less",  # the words are not straight after the number
    ],
)
def test_words_that_are_not_a_limit_after_the_number_give_no_operator(words):
    assert verify.quoted_value("300", words)["op"] is None


def test_a_filled_figure_over_a_limit_written_after_its_number_is_not_met_proven_by_code():
    d = _decide("The stated set pressure shall be 300 psig or less for each valve.")
    assert (
        d["label"] == "Not met"
        and d["code_compare"]["result"] == "fail"
        and d["code_compare"]["read_from"] == "verified quotes"
    )
    assert (
        S.CONTRACTOR_FILLED in d["code"]
        and "no comparison code can read" not in d["code"]
    )
    from app.aim_review.engine import to_line

    line = to_line(1, d)
    assert (
        aim_review_store.shown_label(
            line["label"],
            line["code_compare_json"],
            line["deferred"],
            line["code_note"],
        )
        == aim_review_store.FAIL_BY_CODE
    )


def test_a_figure_under_a_limit_written_after_its_number_is_met_by_code():
    d = _decide("The stated set pressure shall be 400 psig or less.", rule_value="400")
    assert d["label"] == "Met" and d["code_compare"]["result"] == "pass"


def test_an_or_more_limit_is_compared_the_other_way():
    d = _decide(
        "The set pressure shall be 400 psig or more.", rule_value="400"
    )  # 340 >= 400: false
    assert d["label"] == "Not met" and d["code_compare"]["op"] == ">="


def test_forged_numbers_never_make_a_verdict():
    """The model's own numbers only say WHICH value is meant: a rule value that is not in the rule's words, or a paper value that is
    not in the paper's quote, is a Question (no stamp), whatever the label the model gave."""
    rule = "The stated set pressure shall be 300 psig or less for each valve."
    forged_rule = _decide(
        rule, rule_value="250"
    )  # 340 > 250 would "fail" if the model's number were believed
    assert forged_rule["label"] == "Question" and forged_rule["code_compare"] is None
    forged_paper = _decide(
        rule, paper_value="290", label="Met"
    )  # 290 <= 300 would "pass" if believed
    assert forged_paper["label"] == "Question" and forged_paper["code_compare"] is None


def test_a_rule_with_no_operator_anywhere_stays_a_question():
    d = _decide("The stated set pressure is 300 psig for each valve.")
    assert d["label"] == "Question" and d["code_compare"] is None
