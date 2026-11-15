"""R48n point 1 and the lead's order of 15 Nov: a checklist result that rests on a value in conflict, needing an engineer, or carrying two readings is a QUESTION,
never a Pass or Fail, in the classic path and the calculator alike, with every trust switch on or off. Invented data only."""

from __future__ import annotations

import pytest

from app import agent_review_calculator as calc
from app import datasheet_checks, rule_trust, untrusted_value
from app.config import settings
from tests.test_746_relief_valve_checklist import PSV, SHEET, fact
from tests.test_746_relief_valve_checklist import results as psv_results
from tests.test_225_standard_clause_page import _world, temp_storage  # noqa: F401
from tests.test_b1_calculator import FACTS, PAGE

REASON_IN_WORDS = {
    "conflict": "validation state 'conflict'",
    "needs_engineer_review": "validation state 'needs_engineer_review'",
}


def evaluate(facts, equipment_type=None, held=True, monkeypatch=None):
    if not held:  # the evaluator without its second exit: what main does today
        monkeypatch.setattr(
            untrusted_value,
            "hold_results",
            lambda results, *a: results,
        )
    return {
        r["rule_id"]: r
        for r in datasheet_checks.evaluate(
            facts, equipment_type=equipment_type, page_texts={1: PAGE}
        )
    }


def with_state(over):
    return [{**f, **over.get(f["id"], {})} for f in FACTS]


STATES = [
    {"validation_state": "conflict"},
    {"validation_state": "needs_engineer_review"},
    {
        "reading_conflict": "two readings: 10 and 12; the table cell beside the label holds 10; confirm"
    },
]


def test_the_reviewers_case_two_conflicted_facts_give_a_decided_consistency_result_before_and_a_question_after(
    monkeypatch,
):
    both = with_state({"f1": STATES[0], "f2": STATES[0]})
    before = evaluate(both, held=False, monkeypatch=monkeypatch)["DS-C1"]
    assert before["status"] in ("COMPLIANT", "NON_COMPLIANT")  # the hole
    monkeypatch.undo()
    after = evaluate(both)["DS-C1"]
    assert (
        after["status"] == "NEEDS_ENGINEER_REVIEW"
        and after["detail"].startswith("Could not be judged: ")
        and "validation state 'conflict'" in after["detail"]
    )
    assert after["detail"].count("The check read") == 1 and (
        "NON_COMPLIANT" in after["detail"] or "COMPLIANT" in after["detail"]
    )


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("side", ["f1", "f2"])
def test_each_kind_of_untrusted_value_on_either_side_of_a_consistency_pair_holds_it(
    state, side
):
    got = evaluate(with_state({side: state}))["DS-C1"]
    assert got["status"] == "NEEDS_ENGINEER_REVIEW"
    name = "Design pressure" if side == "f1" else "Operating pressure"
    assert name in got["detail"]


def test_trusted_facts_and_an_engineer_confirmed_value_are_untouched():
    plain = evaluate(FACTS)["DS-C1"]
    assert (
        plain["status"] in ("COMPLIANT", "NON_COMPLIANT")
        and plain["status"] != "NEEDS_ENGINEER_REVIEW"
    )
    confirmed = evaluate(
        with_state({"f1": {"validation_state": "conflict", "confirmed_by": "eng"}})
    )["DS-C1"]
    assert confirmed["status"] == plain["status"]


def _psv(state):
    over = [
        f
        for f in SHEET
        if f["field_name"] not in ("set pressure", "max allow working pressure")
    ] + [
        {**fact("set pressure", "13", "barg"), **state},
        fact("max allow working pressure", "12", "barg"),
    ]
    return over


@pytest.mark.parametrize("state", STATES)
def test_a_compared_check_and_a_presence_check_on_an_untrusted_value_are_questions(
    state, monkeypatch
):
    over = _psv(state)
    monkeypatch.setattr(untrusted_value, "hold_results", lambda results, *a: results)
    plain = psv_results(over)
    monkeypatch.undo()
    held = psv_results(over)
    assert (
        plain["PSV-24"]["status"] == "NON_COMPLIANT"
        and held["PSV-24"]["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # compared
    assert (
        plain["PSV-01"]["status"] == "COMPLIANT"
        and held["PSV-01"]["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # presence: stated, but two readings
    assert (
        "Set pressure" in held["PSV-24"]["detail"]
        and "Set pressure" in held["PSV-01"]["detail"]
    )


def test_the_checked_against_side_of_a_compared_check_holds_it_too():
    over = [
        f
        for f in SHEET
        if f["field_name"] not in ("set pressure", "max allow working pressure")
    ] + [
        fact("set pressure", "10", "barg"),
        {
            **fact("max allow working pressure", "12", "barg"),
            "validation_state": "conflict",
        },
    ]
    assert psv_results(over)["PSV-24"]["status"] == "NEEDS_ENGINEER_REVIEW"


@pytest.mark.parametrize("auto_use", [False, True])
@pytest.mark.parametrize("tested_cards", [False, True])
def test_no_trust_switch_lifts_the_hold_and_a_sign_off_cannot_either(
    monkeypatch, auto_use, tested_cards
):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", auto_use)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", tested_cards)
    held = psv_results(_psv(STATES[0]))["PSV-24"]
    assert held["status"] == "NEEDS_ENGINEER_REVIEW"
    label = rule_trust.check_label(
        {**held, "checklist": True, "draft": False, "local": False}
    )  # an item an engineer signed off later
    assert label == rule_trust.ENGINEER_CONFIRMED
    assert (
        rule_trust.apply_trust(held, label)["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # the label never lifts a hold


def test_the_classic_path_stores_the_question_not_a_breach(temp_storage):  # noqa: F811
    from app import db

    held = psv_results(_psv(STATES[0]))["PSV-24"]
    _std, run = _world(["x"])
    sheet = (
        db.connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id=?", (run,))
        .fetchone()[0]
    )
    written = datasheet_checks.store(run, sheet, [held], pages_read={})
    rows = (
        db.connect()
        .execute(
            "SELECT compliance_status, origin FROM review_findings WHERE review_run_id=?",
            (run,),
        )
        .fetchall()
    )
    assert [r["compliance_status"] for r in rows] == [
        "NEEDS_ENGINEER_REVIEW"
    ] and written[0]["compliance_status"] == "NEEDS_ENGINEER_REVIEW"


def test_the_calculator_makes_a_question_line_never_a_pass_or_fail():
    results = list(
        datasheet_checks.evaluate(
            with_state({"f1": STATES[0], "f2": STATES[0]}),
            equipment_type=None,
            page_texts={1: PAGE},
        )
    )
    lines = [
        x
        for x in calc.checklist_lines(
            results,
            page_texts={1: "Design pressure 10 bar. Operating pressure 12 bar."},
        )
        if x["rule_id"] == "DS-C1"
    ]
    assert lines and all(x["verdict"] == "Query" for x in lines)


def test_nothing_is_held_when_no_fact_is_untrusted():
    r = [{"status": "COMPLIANT", "rule_id": "X", "role": "r", "fact_id": "f"}]
    assert (
        untrusted_value.hold_results(
            r, [{"id": "f", "field_name": "x", "field_label": "X"}], {}, frozenset()
        )
        == r
    )
    assert (
        untrusted_value.hold_results(
            [], [{"id": "f", "validation_state": "conflict"}], {}, frozenset()
        )
        == []
    )


def _kit_row(fact_id="f1"):
    # a kit card's pass: already a question that remembers what the rule read
    return {
        "rule_id": "PSV-24",
        "status": "NEEDS_ENGINEER_REVIEW",
        "rule_said": "COMPLIANT",
        "kit": True,
        "checklist": True,
        "role": "set_pressure",
        "fact_id": fact_id,
        "equipment_tag": None,
        "detail": "tested card",
        "hold_reason": "rule_not_proven",
    }


def _hold(row, facts):
    from app import datasheet_roles

    rules = datasheet_checks.load_rules()
    return untrusted_value.hold_results(
        [row], facts, rules, datasheet_roles.wanted_roles(PSV, rules)
    )[0]


@pytest.mark.parametrize("state", STATES)
def test_a_kit_card_pass_on_an_untrusted_value_is_no_longer_a_pass_in_the_list_of_passes(
    state,
):
    f = {**fact("set pressure", "10", "barg"), "id": "f1", **state}
    held = _hold(_kit_row(), [f])
    assert (
        held["rule_said"] is None
        and held["status"] == "NEEDS_ENGINEER_REVIEW"
        and held["hold_reason"] == "other"
    )
    assert (
        held["detail"].startswith("Could not be judged: Set pressure: ")
        and "The check read COMPLIANT" in held["detail"]
    )


def test_a_kit_card_pass_on_a_trusted_value_is_untouched_and_a_kit_row_that_said_nothing_is_too():
    f = {**fact("set pressure", "10", "barg"), "id": "f1"}
    row = _kit_row()
    assert _hold(row, [f]) == row
    bad = {**f, "validation_state": "conflict"}
    undecided = {**row, "rule_said": None}
    assert _hold(undecided, [bad]) == undecided  # it never claimed a pass
