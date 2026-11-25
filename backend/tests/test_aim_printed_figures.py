"""A pass stated as a Question (planner's live check of 26 Nov 2026: two valve cards were sent as Questions whose ask only stated
a pass). Two causes, both fixed by code from the judge's structured answer, never from its words: the judge gave a figure it had
CONVERTED, so code could not find it in the quote and never compared; and a Met the judge gave that code could not prove fell
back to a sent Question. Invented papers and rules; no model."""

from __future__ import annotations

from app import aim_review
from app.aim_review import prompts as P
from app.aim_review import steps as S
from app.aim_review.engine import to_line
from app.aim_review.paper import Paper
from app.aim_review.verify import converted_value

QUOTE = "Invented relief setting: 150 psig"
PAPER = Paper(
    paper_id="doc_inv_sheet",
    pages={1: f"Invented sheet.\n{QUOTE}\nInvented design figure: 15 barg\n"},
)


def _item(rule_quote: str) -> dict:
    return {"id": "C001", "book": "B1", "book_id": "b1", "clause": "7.2", "source": S.HELD, "topic": "invented setting",
            "what_to_check": "the invented setting within the rule's limit", "applies_when": "always",
            "rule_quote": rule_quote, "paper_fields": ["setting"], "paper_pages": [1], "kind": "limit"}  # fmt: skip


def _answer(label: str, numbers: dict, **over) -> dict:
    return {"id": "C001", "label": label, "field": "setting", "page": 1, "quote": QUOTE, "numbers": numbers,
            "comment": "Invented words.", **over}  # fmt: skip


RULE = _item("The invented setting shall not exceed 12 barg.")
CONVERTED = {
    "paper_value": "10.34",
    "paper_unit": "barg",
    "operator": "<=",
    "rule_value": "12",
    "rule_unit": "barg",
}


def test_a_figure_the_judge_converted_is_matched_to_the_printed_one_and_code_compares_it():
    line = S._decide(RULE, _answer("Question", CONVERTED), PAPER, {}, "")
    assert (
        line["label"] == "Met" and line["code_compare"]["result"] == "pass"
    )  # 150 psig is 10.34 barg, within 12 barg
    assert (
        line["code_compare"]["paper"] == [150.0, "psig"]
        and "code read the printed figure" in line["code"]
    )
    fails = S._decide(_item("The invented setting shall not exceed 9 barg."), _answer("Question", {**CONVERTED, "rule_value": "9"}),
                      PAPER, {}, "")  # fmt: skip
    assert fails["label"] == "Not met"


def test_only_one_printed_figure_of_the_same_quantity_and_reference_matches():
    assert converted_value("10.34", "barg", QUOTE)["value"] == "150"
    assert (
        converted_value("10.34", "bara", QUOTE) is None
    )  # gauge is never matched with absolute
    assert (
        converted_value("11", "barg", QUOTE) is None
    )  # not the printed figure converted
    assert (
        converted_value("10.34", "barg", "Invented: 150 psig inlet, 150 psig outlet")
        is None
    )  # two such figures
    assert (
        converted_value("10.34", "barg", "Invented: 150 mm") is None
    )  # another quantity


def test_a_met_the_judge_gave_that_code_could_not_prove_is_kept_on_all_points_and_never_sent():
    worked_out = {
        "paper_value": "150",
        "paper_unit": "psig",
        "operator": ">=",
        "rule_value": "120.5",
        "rule_unit": "psig",
    }
    line = S._decide(_item("The setting shall be at least ten percent above the invented operating figure."),
                     _answer("Met", worked_out), PAPER, {}, "")  # fmt: skip
    assert line["label"] == "Question" and aim_review.AI_MET_UNPROVEN in line["code"]
    assert (
        not aim_review.sendable(to_line(1, line))
        and line["comment"] == "Invented words."
    )


def test_a_question_whose_numbers_pass_is_still_sent_its_words_are_never_read():
    """A judge's numbers may show that a CONDITION holds (above a threshold, so a requirement applies): never hidden by code."""
    condition = {
        "paper_value": "150",
        "paper_unit": "psig",
        "operator": ">",
        "rule_value": "100",
        "rule_unit": "psig",
    }
    line = S._decide(_item("Above the invented threshold an invented test applies."), _answer("Question", condition), PAPER,
                     {}, "")  # fmt: skip
    assert aim_review.AI_MET_UNPROVEN not in (
        line["code"] or ""
    ) and aim_review.sendable(to_line(1, line))


def test_the_judge_is_told_to_give_every_value_as_printed():
    assert "exactly as PRINTED (never converted or worked out" in P.S4_TASK
