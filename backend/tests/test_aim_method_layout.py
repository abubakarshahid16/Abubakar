"""A form printed in two halves side by side (18 Nov 2026: the strict judges marked comments WRONG that set one half's value
against the other half's heading): the model reads such a page as its left half, then its right half, under one page number;
the quote check still reads the page as stored. Invented page; no paid call."""

from __future__ import annotations

from app.aim_review import layout as LY
from app.aim_review.paper import Paper
from app.aim_review.steps import paper_block
from app.aim_review.verify import quote_in

LEFT = ["MAIN BLOCK (1.1)", "FLOW RATE  ____12____ m3/h", "HEAD  ____40____ m", "SPEED  ____*____ rpm", "COAT  ____7____",
        "SIZE  ____3____", "MASS  ____9____ kg", "TEMP  ____60____ C", "PRESS  ____5____ bar", "OILING  ____RING____"]  # fmt: skip
RIGHT = ["SIDE BLOCK (2.1)", "Kind  ___ALPHA___", "Frame  ___B2___", "Mount  ___FOOT___", "Power  ___*___ kW",
         "Poles  ___4___", "Volt  ___400___", "Hertz  ___50___", "Enclosure  ___TE___", "OILING  ___GREASE___"]  # fmt: skip
FORM = "\n".join(
    f"{n:>2}   {a:<44}{b}" for n, (a, b) in enumerate(zip(LEFT, RIGHT, strict=True), 1)
)


def test_a_two_half_page_is_shown_as_its_left_half_then_its_right_half():
    left, right = LY.halves(FORM)
    assert "GREASE" not in left and "RING" in left and "MAIN BLOCK" in left
    assert (
        right.splitlines()[0] == "SIDE BLOCK (2.1)"
        and right.splitlines()[-1] == "OILING  ___GREASE___"
    )
    block = paper_block(Paper(paper_id="d", pages={2: FORM}))
    assert (
        "=== PAGE 2 (left half) ===" in block and "=== PAGE 2 (right half) ===" in block
    )
    assert block.index("RING") < block.index("SIDE BLOCK") < block.index("GREASE")


def test_a_quote_from_one_half_still_stands_on_the_stored_page():
    assert quote_in("OILING  ___GREASE___", FORM) and quote_in(
        "FLOW RATE  ____12____ m3/h", FORM
    )


def test_prose_a_short_page_and_a_label_value_gap_are_never_split():
    prose = "\n".join(
        f"Line {i} of an invented procedure: the team reviews each node in turn."
        for i in range(20)
    )
    assert (
        LY.split_at(prose) is None
        and LY.split_at("\n".join(FORM.splitlines()[:5])) is None
    )
    one_half = "\n".join(
        f"{n:>2}   {a}" for n, a in enumerate(LEFT * 2, 1)
    )  # labels and values only: no right half
    assert LY.split_at(one_half) is None
    assert (
        paper_block(Paper(paper_id="d", pages={1: prose})).count("=== PAGE 1 ===") == 1
    )


def test_the_judge_is_told_a_question_carries_no_verdict_and_pairs_slash_fields_in_order():
    from app.aim_review import prompts as P

    assert (
        'A "Question" ASKS: its comment never says that a value passes, fails'
        in P.S4_TASK
    )
    assert "pairs them in order" in P.S4_TASK and "SAME quantity" in P.S4_TASK
