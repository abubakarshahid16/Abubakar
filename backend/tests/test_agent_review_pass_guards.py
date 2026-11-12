"""A textual Pass (a rule without numbers) needs the rule's own field and, for a conditional rule, the condition quoted (W2, 12 Nov).

Invented paper, rule book and model. A guard can only take a Pass away: never a Fail, never a number rule."""

# ruff: noqa: F811
from __future__ import annotations

import itertools
import json

import pytest

from app import agent_review_pass_guards as G
from app import agent_review_request as request_mod
from app import agent_review_verdict as V
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of

PAGES = {
    1: "DATA SHEET\nCoating layers two\nMarking blue\nBody: carbon steel\nSerial invented"
}


def stored(run_id, iid):
    return json.loads(lines_of(run_id)[iid]["line_json"])


SPACED = "DATA SHEET\nCoating layers two\nfiller line one\nfiller line two\nMarking blue\nfiller line three\nfiller line four\nSerial invented"


def only(w, iid="R-coat", **answer):
    from app import db

    with (
        db.connect() as conn
    ):  # the label and its value on neighbouring lines, the other fields further away
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ?", (SPACED, s.PAPER)
        )
    w["fake"].answers = {iid: {**s.ANSWERS[iid], **answer}}


def test_a_pass_on_the_rules_own_field_line_stays_proven(w):
    only(w)
    assert lines_of(run_review())["R-coat"]["word"] == "Pass"


def test_a_pass_quoted_on_another_fields_line_is_ai_thinks_met_with_a_plain_reason(w):
    only(
        w, paper_quote="Marking blue"
    )  # the rule's field is the coating layers; this is the marking line
    run_id = run_review()
    row, line = lines_of(run_id)["R-coat"], stored(run_id, "R-coat")
    assert (row["verdict_class"], row["word"]) == (
        "AI opinion, engineer to confirm",
        "AI thinks: met",
    )
    assert (
        row["reason"] == "the quoted line is not the coating layers line"
        and line["reason_code"] == G.CODE_FIELD_NOT_QUOTED
    )


def test_a_rule_whose_field_is_not_known_is_never_a_proven_pass(w):
    for it in w["doc"]["items"]:
        if it["item_id"] == "R-coat":
            it["rule_label"] = {**it["rule_label"], "field": None}
    only(w)
    run_id = run_review()
    assert (
        lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_FIELD_UNKNOWN
    )


def test_the_ais_own_field_label_is_never_evidence(w):
    only(
        w, paper_quote="Marking blue", field_label="Coating layers"
    )  # the AI says the field is the right one; the line is not
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


@pytest.fixture
def conditional(monkeypatch):
    quote = "The coating shall be applied in two layers when installed outdoors."
    monkeypatch.setitem(s.RULES, "R-coat", (quote, "4.4", None, None, None, None))
    return quote


def test_a_conditional_rule_needs_a_verified_quote_for_the_condition(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    only(w, clause_quote=conditional)
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == (
        "AI opinion, engineer to confirm",
        "AI thinks: met",
    )
    assert (
        row["reason"] == G.CONDITION_NOT_QUOTED_WHY
        and stored(run_id, "R-coat")["reason_code"] == G.CODE_CONDITION_NOT_QUOTED
    )


def test_a_condition_quote_that_is_not_on_the_page_does_not_count(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    only(
        w,
        clause_quote=conditional,
        condition_quote="Installed outdoors in a sour service",
        condition_page=1,
    )
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


def test_a_verified_condition_quote_lets_the_pass_stand(w, conditional):
    w["doc"], w["cache"] = s.item_doc()
    only(
        w, clause_quote=conditional, condition_quote="Serial invented", condition_page=1
    )
    assert lines_of(run_review())["R-coat"]["word"] == "Pass"


def test_a_fail_is_never_changed_by_these_guards(w):
    only(
        w, "R-mark", paper_quote="Coating layers two"
    )  # another field's line: a Pass would lose proof, a Fail must not
    assert lines_of(run_review())["R-mark"]["word"] == "Fail"


def test_a_number_rule_with_a_code_comparison_is_untouched(w):
    for it in w["doc"]["items"]:
        if it["item_id"] == "R-frame":
            it["rule_label"] = {**it["rule_label"], "field": "something_else"}
    w["fake"].answers = {"R-frame": s.ANSWERS["R-frame"]}
    from app import db

    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ?", (s.PAPER_PAGE, s.PAPER)
        )
    assert lines_of(run_review())["R-frame"]["word"] == "Pass"


def test_the_answer_shape_has_the_condition_slot_and_the_prompt_asks_for_it():
    assert (
        "condition_quote" in request_mod.ANSWER_SHAPE
        and "condition_page" in request_mod.ANSWER_SHAPE
    )
    assert "condition_quote" in request_mod.SYSTEM


# ---------------------------------------------------------------- pure: the one function and the brute force


@pytest.mark.parametrize(
    "text,want",
    [
        ("Springs for sour service shall be protected.", True),
        ("The unit shall be tested when delivered.", True),
        ("Where a rupture disc is used the gauge is fitted.", True),
        ("A relief valve for hydrogen service shall have a bonnet.", True),
        ("The valve shall be fitted if specified.", True),
        ("The coating shall be applied in two layers.", False),
        ("The service life shall be 25 years.", False),
        ("The valve shall be supplied with a test certificate for every unit.", False),
        ("The nameplate shall be of stainless steel.", False),
    ],
)
def test_is_conditional_sees_for_service_forms_and_not_near_misses(text, want):
    assert V.is_conditional(text) is want


def test_quote_lines_are_the_page_lines_the_quote_lies_on_and_their_neighbours_on_request():
    assert G.quote_lines(PAGES[1], "Marking blue") == ["marking blue"]
    assert G.quote_lines(PAGES[1], "Marking blue", 1) == [
        "coating layers two",
        "marking blue",
        "body: carbon steel",
    ]
    assert G.quote_lines(PAGES[1], "Coating layers two\nMarking blue") == [
        "coating layers two",
        "marking blue",
    ]
    assert G.quote_lines(PAGES[1], "not on the page") == []


def _item(field, number):
    return {
        "item_id": "R-1",
        "source": "rule",
        "rule_kind": "limit" if number else None,
        "field_roles": [],
        "rule_label": {"field": field},
    }


def test_no_line_shape_keeps_a_textual_pass_unless_the_field_belongs_and_a_condition_is_quoted():
    kept = 0
    for (
        number,
        known,
        on_field,
        conditional_,
        cond_quote,
        in_requirement,
    ) in itertools.product([False, True], repeat=6):
        quote = "Coating layers two" if on_field else "Marking blue"
        clause = (
            "The coating shall be in two layers when outdoors."
            if conditional_ and not in_requirement
            else "The coating shall be in two layers."
        )
        requirement = (
            "It applies when outdoors." if conditional_ and in_requirement else None
        )
        answer = {"paper_page": 1, "paper_quote": quote, "clause_quote": clause}
        if cond_quote:
            answer.update(condition_quote="Serial invented", condition_page=1)
        got = G.check(
            _item("coating_layers" if known else None, number),
            answer,
            {1: SPACED},
            requirement,
        )
        passes = got is None
        want = number or (known and on_field and (not conditional_ or cond_quote))
        assert passes is bool(want), (
            number,
            known,
            on_field,
            conditional_,
            cond_quote,
            in_requirement,
        )
        kept += passes
    assert kept > 0


def test_every_reason_of_the_module_states_only_what_the_code_saw():
    banned = (
        "does not state",
        "not mentioned",
        "absent",
        "missing",
        "wrong",
        "incorrect",
    )
    for name in ("FIELD_UNKNOWN_WHY", "FIELD_LINE_WHY", "CONDITION_NOT_QUOTED_WHY"):
        assert not any(b in getattr(G, name).lower() for b in banned), name


def test_a_label_on_the_neighbouring_line_counts_and_one_further_away_does_not():
    item = _item("coating_layers", False)
    assert (
        G.belongs(item, "Marking blue", PAGES[1])[0] is True
    )  # the label line is directly above
    assert (
        G.belongs(item, "Marking blue", SPACED)[0] is False
    )  # two filler lines between
