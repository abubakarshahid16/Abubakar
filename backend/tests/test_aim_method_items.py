"""A value belongs to its equipment item (owner, 18 Nov 2026 after live): a line that sets one item's value against another item's
is no finding when both items are verified on their pages and differ. Anything code cannot verify changes nothing, so a real
conflict of one item's values stays sent. Invented paper; no paid call."""

from __future__ import annotations

import json
import re

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import items as I
from app.aim_review import prompts as P
from app.aim_review.engine import to_line
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

PAGES = {
    2: "INVENTED DRIVER BLOCK\nLube: grease, sealed for life\n",
    3: "INVENTED MAIN ITEM BLOCK\nLubrication: ring oil to the bearing housing\n",
}
DOC = Paper(paper_id="doc_items", pages=PAGES)
LINE = {
    "label": "Question",
    "page": 3,
    "quote": "Lubrication: ring oil to the bearing housing",
    "code": "",
    "code_compare": None,
}
OTHER = {"page": 2, "quote": "Lube: grease, sealed for life"}


def _j(items, other=OTHER):
    return {"other": other, "items": items}


def test_values_of_two_different_items_are_no_finding_and_not_sent():
    d = I.check(
        dict(LINE), _j(["INVENTED MAIN ITEM BLOCK", "INVENTED DRIVER BLOCK"]), DOC
    )
    assert d["code"].startswith(
        'different_items: page 3 "INVENTED MAIN ITEM BLOCK" / page 2 "INVENTED DRIVER BLOCK"'
    )
    assert not aim_review.sendable(to_line(1, d))


@pytest.mark.parametrize(
    "j",
    [
        _j(
            ["INVENTED MAIN ITEM BLOCK", "INVENTED MAIN ITEM BLOCK"]
        ),  # the same item: a real conflict stays
        _j(
            ["INVENTED MAIN ITEM BLOCK", "BLOCK"]
        ),  # one name inside the other (both on their pages): the same item
        _j(
            ["INVENTED MAIN ITEM BLOCK", "AN ITEM NOT ON THAT PAGE"]
        ),  # an item code cannot find on its page
        _j(
            ["INVENTED MAIN ITEM BLOCK", "INVENTED DRIVER BLOCK"],
            {"page": 2, "quote": "words not on the page"},
        ),
        _j(["INVENTED MAIN ITEM BLOCK"]),  # not two items
        {
            "items": ["INVENTED MAIN ITEM BLOCK", "INVENTED DRIVER BLOCK"]
        },  # no second value
        None,
    ],
)
def test_anything_code_cannot_verify_changes_nothing(j):
    """Still sent, never "different items"; when the judge named two items code did not accept, the reason is recorded."""
    d = I.check(dict(LINE), j, DOC)
    assert "different_items" not in d["code"] and aim_review.sendable(to_line(1, d))
    named = (
        isinstance(j, dict)
        and isinstance(j.get("other"), dict)
        and len(j.get("items") or []) == 2
    )
    assert d["code"].startswith(I.ITEMS_NOT_ACCEPTED) if named else d["code"] == ""


def test_a_met_and_a_held_rule_comparison_are_never_touched():
    j = _j(["INVENTED MAIN ITEM BLOCK", "INVENTED DRIVER BLOCK"])
    assert I.check({**LINE, "label": "Met"}, j, DOC)["code"] == ""
    held = {**LINE, "code_compare": {"result": "fail", "read_from": "verified quotes"}}
    assert I.check(held, j, DOC)["code"] == ""
    paper_pair = {
        **LINE,
        "code_compare": {"result": "fail", "read_from": "verified paper quotes"},
    }
    assert I.check(paper_pair, j, DOC)["code"].startswith("different_items")


def test_the_judge_is_asked_for_the_item_of_each_value():
    assert (
        '"items": ["item of quote", "item of other"]' in P.S4_TASK
        and "SAME item" in P.S4_TASK
    )


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_a_run_keeps_a_cross_item_line_off_the_comments(aim_db):
    def judge(step, cached, prompt):
        ids = re.findall(r'"id": "([CG]\d+)"', prompt)
        first = {"id": ids[0], "label": "Question", "page": 1, "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
                 "field": "f", "comment": "c", "other": {"page": 2, "quote": "Body material of the test item: carbon steel to the buyer list"},
                 "items": ["Design pressure", "Body material"]}  # fmt: skip
        return {"judgments": [first] + [{"id": i, "label": "Met", "page": 1, "quote": "Design pressure of the test item: 12 bar gauge at the inlet",
                                         "field": "f", "comment": "c"} for i in ids[1:]]}  # fmt: skip

    model = E.FakeModel(
        kind="datasheet", subject_key="test_item", answers={"aim_judge": judge}
    )
    r = aim_review.run(aim_db, run_id="run_items", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    marked = [ln for ln in r.lines if "different_items" in (ln["code_note"] or "")]
    assert (
        r.status == "done"
        and marked
        and not any(aim_review.sendable(ln) for ln in marked)
    )
    assert json.dumps(marked)  # stays a point (All points)


# A form printed in two columns side by side (invented): one line of the page holds a field of each block.
TWO_COL = {
    2: (
        "                 MAIN BLOCK (1.2)                                          SIDE BLOCK (3.4)\n"
        "\n"
        "   FLOW RATE          ____12____ m3/h                                Kind              ___ALPHA___\n"
        "\n"
        "   COAT               ____7_____                                     OILING            ___GREASE___\n"
    ),
    3: (
        "              BEARING AND OILING (6.1)\n"
        "\n"
        "   OILING :           (6.2)                ____RING OIL____\n"
    ),
}
COLS = Paper(paper_id="doc_cols", pages=TWO_COL)
GREASE = "OILING            ___GREASE___"
RING = "OILING :           (6.2)                ____RING OIL____"


def test_a_value_belongs_to_the_heading_of_its_own_column():
    assert (
        I.heading_of(TWO_COL[2], GREASE) == "side block"
    )  # not the heading at the start of the line
    assert I.heading_of(TWO_COL[2], "COAT               ____7_____") == "main block"
    assert I.heading_of(TWO_COL[3], RING) == "bearing and oiling"


def test_a_label_with_a_fill_in_or_a_figure_is_no_heading():
    page = "   FLOW RATE          ____12____ m3/h\n   COAT  ____7_____\n"
    assert I.heading_of(page, "COAT  ____7_____") == ""
    assert (
        I.heading_of("   12.5 @ 40 OC (OF)\n   COAT  ____7_____\n", "COAT  ____7_____")
        == ""
    )


def test_items_named_in_the_judges_words_are_checked_against_the_headings_code_finds():
    """The judge's names need not be printed word for word: a name that shares a word with the heading above its value counts."""
    line = {**LINE, "page": 3, "quote": RING}
    j = _j(
        ["Bearings of the main item", "Side block (invented)"],
        {"page": 2, "quote": GREASE},
    )
    d = I.check(dict(line), j, COLS)
    assert d["code"].startswith("different_items") and not aim_review.sendable(
        to_line(1, d)
    )


def test_two_values_under_one_heading_are_one_item_whatever_the_names():
    pages = {2: TWO_COL[3], 3: TWO_COL[3].replace("RING OIL", "SPLASH")}
    line = {**LINE, "page": 3, "quote": RING.replace("RING OIL", "SPLASH")}
    d = I.check(
        dict(line),
        _j(["Bearing", "Oiling"], {"page": 2, "quote": RING}),
        Paper(paper_id="d", pages=pages),
    )
    assert d["code"].startswith(
        f"{I.ITEMS_NOT_ACCEPTED}: the same item"
    ) and aim_review.sendable(to_line(1, d))


def test_the_judge_is_told_to_read_the_heading_of_the_values_own_column():
    assert "ON ITS OWN SIDE" in P.S4_TASK and "ALWAYS give both" in P.S4_TASK
