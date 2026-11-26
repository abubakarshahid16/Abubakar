"""The formula check library (planner 25 Nov 2026, item 3): points the paper decides by code, on a held clause. Invented values and an
invented clause sentence only; no model."""

from __future__ import annotations

import json

import pytest

from app import aim_review, aim_review_store
from app.aim_review import fail_words
from app.aim_review import formulas as F
from app.aim_review.paper import Paper
from app.aim_review.verify import find_page

CLAUSE = "The stated design pressure of the invented unit shall be at least the most severe operating pressure of the invented unit."
SET = "A relief device of the invented unit shall be set at or below the invented limit; no device may be set above 110 % of the limit."
TEST = "The invented test shall be at least equal to 1.3 times the invented limit."
CHECKS = {
    "version": "1",
    "checks": [
        {"id": "design_pressure", "title": "Design pressure covers the operating pressure", "ref": "X-1", "probe": "shall be at least the most severe operating pressure",
         "left": ["design_pressure"], "right": ["max_operating_pressure", "operating_pressure"], "met": [">=", 1.0], "not_met": ["<", 1.0],
         "words": "the stated design pressure {a} is {rel} the operating pressure {b}"},
        {"id": "set_pressure", "title": "Set pressure against the limit", "ref": "X-2", "probe": "no device may be set above (?P<factor>110) % of the limit",
         "left": ["set_pressure"], "right": ["mawp"], "met": ["<=", 1.0], "not_met": [">", "percent"],
         "words": "the stated set pressure {a} is {rel} the limit {b}"},
        {"id": "hydrotest", "title": "Test pressure against the limit", "ref": "X-3", "probe": "at least equal to (?P<factor>1\\.3|1\\.5) times the invented limit",
         "left": ["test_pressure"], "right": ["mawp"], "met": None, "not_met": ["<", "factor"],
         "words": "the stated test pressure {a} is {rel} {f} times the limit {b}"},
    ],
}  # fmt: skip


@pytest.fixture(autouse=True)
def invented_checks(tmp_path, monkeypatch):
    path = tmp_path / "checks.json"
    path.write_text(json.dumps(CHECKS))
    monkeypatch.setattr(F, "PATH", path)
    F._checks.cache_clear()
    monkeypatch.setattr(
        F,
        "_carried",
        lambda conn, ids: {"b1": ("STD-X", {7: CLAUSE + " " + SET + " " + TEST})},
    )
    yield
    F._checks.cache_clear()


def paper(*rows: str) -> Paper:
    return Paper(paper_id="p", pages={1: "\n".join(rows)})


def run(*rows: str):
    return F.lines(None, paper(*rows), ["b1"])


# ---- reading the paper's values


@pytest.mark.parametrize(
    ("cell", "want"),
    [
        ("9 / 7.5 barg (Note 3)", [(9, 9, "barg"), (7.5, 7.5, "barg")]),
        ("-5 to 90OC / 60OC", [(-5, 90, "C"), (60, 60, "C")]),
        ("3.5 bar (ga)", [(3.5, 3.5, "barg")]),
        ("200 psig (By Contractor)", [(200, 200, "psig")]),
        ("29 psig / -", [(29, 29, "psig"), None]),
    ],
)
def test_the_values_of_a_cell_are_read_with_their_units(cell, want):
    got = F.parse_value(cell)
    assert [None if v is None else (v.low, v.high, v.unit) for v in got] == want


@pytest.mark.parametrize(
    "cell",
    [
        "By Contractor",
        "psig (By Contractor)",
        "TBA",
        "TBD",
        "*",
        "----",
        "see note 3",
        "10 to",
    ],
)
def test_a_value_left_open_or_not_a_number_is_no_value_never_a_guess(cell):
    assert F.parse_value(cell) is None


# ---- the checks


def test_a_design_pressure_below_the_operating_pressure_is_not_met_proven_by_code():
    (line,) = run("Design pressure   10 barg", "Maximum operating pressure   12 barg")
    assert (
        line["label"] == "Not met"
        and line["clause"] == "X-1"
        and line["standard"] == "STD-X"
    )
    assert (
        line["comment"].startswith(fail_words.PROVEN_FAIL)
        and "Design pressure" in line["comment"]
        and "Maximum operating pressure" in line["comment"]
    )
    assert fail_words.proven_fail(
        line["label"], line["code_compare"], line["deferred"], [line["code"]]
    )
    assert (
        aim_review_store.shown_label(
            line["label"], json.dumps(line["code_compare"]), False, line["code"]
        )
        == aim_review_store.FAIL_BY_CODE
    )


def test_a_design_pressure_that_covers_it_is_met_and_makes_no_comment():
    (line,) = run("Design pressure   12 barg", "Operating pressure   10 barg")
    assert line["label"] == "Met" and line["comment"] == ""
    assert not aim_review.sendable(
        {**{"label": "Met"}, "code_note": line["code"]}
    )  # a pass is a point, never a comment


def test_a_combined_row_and_a_two_cell_row_are_both_read():
    (a,) = run("Design/Operating pressure   10 / 12 barg (Note 3)")
    assert a["label"] == "Not met" and a["quote"].startswith(
        "Design/Operating pressure"
    )
    (b,) = run(
        "Internal design pressure :   3.5   bar (ga)",
        "Maximum operating pressure :   3.8   bar (ga)",
    )
    assert b["label"] == "Not met" and "3.5 bar (ga)" in b["quote"]


def test_every_line_quotes_a_row_code_finds_on_its_page():
    rows = ("Design pressure   10 barg", "Maximum operating pressure   12 barg")
    p = paper(*rows)
    for line in F.lines(None, p, ["b1"]):
        assert (
            find_page(line["quote"], p.pages, line["page"]) == line["page"]
        )  # a verified quote of the paper, not a model's number


def test_a_value_the_paper_does_not_state_makes_no_line_a_forged_number_cannot_make_one():
    assert run("Design pressure   10 barg") == []  # the other value is not on the page
    assert (
        run("Design pressure   10 barg", "Operating pressure   By Contractor") == []
    )  # left open: a Question
    assert run("Design pressure   10 barg", "Operating pressure   TBA") == []
    assert run("Some other row   5 bar", "Operating pressure   12 barg") == []


def test_a_label_that_stands_twice_on_a_page_is_not_guessed_between():
    assert (
        run(
            "Design pressure   10 barg",
            "Design pressure   14 barg",
            "Operating pressure   12 barg",
        )
        == []
    )


def test_a_gauge_value_is_never_set_against_an_unmarked_one():
    assert run("Design pressure   10 bar", "Operating pressure   12 barg") == []
    (line,) = run(
        "Design pressure   10 barg", "Operating pressure   100 psig"
    )  # two gauge units: converted by the app's unit code
    assert (
        line["label"] == "Met"
        and line["code_compare"]["read_from"] == "verified quotes"
    )


def test_a_clause_not_in_a_carried_book_checks_nothing(monkeypatch):
    monkeypatch.setattr(
        F,
        "_carried",
        lambda conn, ids: {"b1": ("STD-X", {1: "Nothing about any limit here."})},
    )
    assert run("Design pressure   10 barg", "Operating pressure   12 barg") == []
    monkeypatch.setattr(F, "_carried", lambda conn, ids: {})
    assert run("Design pressure   10 barg", "Operating pressure   12 barg") == []


def test_the_set_pressure_is_proven_only_where_the_clause_proves_it():
    assert (
        run("Set pressure   12 barg", "Max. allow. working pressure   10 barg")[0:0]
        == []
    )
    rows = {"above": ("Set pressure   12 barg", "Max. allow. working pressure   10 barg"), "between": ("Set pressure   10.5 barg", "MAWP   10 barg"),
            "at": ("Set pressure   10 barg", "Max. allow. working pressure   10 barg")}  # fmt: skip
    got = {
        k: [line["label"] for line in run(*v) if line["item_id"] == "F-set_pressure"]
        for k, v in rows.items()
    }
    assert got == {
        "above": ["Not met"],
        "between": [],
        "at": ["Met"],
    }  # 105 % of the limit: the clause is silent: a Question stays


def test_the_hydrotest_check_proves_a_low_test_never_a_sufficient_one_and_reads_its_factor_from_the_clause():
    low = [
        x
        for x in run("Hydrotest pressure   12 barg", "MAWP   10 barg")
        if x["item_id"] == "F-hydrotest"
    ]
    assert [x["label"] for x in low] == ["Not met"] and "1.3" in low[0]["comment"]
    ok = [
        x
        for x in run("Hydrotest pressure   13 barg", "MAWP   10 barg")
        if x["item_id"] == "F-hydrotest"
    ]
    assert (
        ok == []
    )  # the clause multiplies by a stress ratio the paper does not state: "enough" is not proven


def test_a_range_is_judged_at_its_upper_end_and_a_filled_in_figure_carries_its_note():
    from app.aim_review.formulas import parse_value

    assert parse_value("-5 to 70OC")[0].high == 70
    (line,) = run(
        "Set pressure   200 psig (By Contractor)",
        "Max. allow. working pressure   10 barg",
    )
    assert (
        line["label"] == "Not met" and "filled in" in line["code"]
    )  # a figure beside a who-supplies note is a stated value (owner, 18 Nov)


def test_a_bad_check_file_checks_nothing_and_never_stops_a_review(
    tmp_path, monkeypatch
):
    path = tmp_path / "broken.json"
    path.write_text("not json")
    monkeypatch.setattr(F, "PATH", path)
    F._checks.cache_clear()
    assert (
        F.checks() == ()
        and run("Design pressure   10 barg", "Operating pressure   12 barg") == []
    )
