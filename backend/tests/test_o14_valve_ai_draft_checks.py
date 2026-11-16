"""Order 14, lane A: two valve numbers of SAES-J-600 (inlet piping pressure drop at most 3% and stated, 9.7.2; a conventional valve
only below 10% back pressure, 5.1.1) are compared by CODE in the checklist data, marked "AI draft, engineer to confirm". Their cards
declare what they need, so they never decide; the calculator never makes a Pass or Fail of them: a limit not met, or a value not
given, is a Query; a limit met is no line. Invented values only.
"""

from __future__ import annotations

from app import agent_review_calculator as calc
from app import card_trust
from app import datasheet_checks as dc

PSV = "Pressure Safety Valve"
DRAFTS = ("PSV-A01", "PSV-A02")


def fact(name, value, unit=None, *, label=None, page=2):
    return {
        "id": f"f-{name}-{value}",
        "field_name": name,
        "field_label": label or name.capitalize(),
        "field_value": f"{value} {unit}".strip() if unit else value,
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 0,
        "blank_marker": None,
        "value_note": None,
        "page": page,
        "equipment_tag": None,
    }


def results(facts):
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
        if r.get("checklist")
    }


def test_each_ai_draft_item_cites_a_page_of_saes_j_600_says_it_is_a_draft_and_never_decides():
    items = {i["id"]: i for i in dc.checklist_for(PSV, dc.load_rules())["items"]}
    assert set(DRAFTS) == calc.ai_draft_ids()
    for i in DRAFTS:
        item = items[i]
        assert (
            item["source"]["standard"] == "SAES-J-600"
            and item["source"]["clause"]
            and item["source"]["page"] >= 1
        )
        assert calc.AI_DRAFT_WORDS in item["text"]
        assert card_trust.why_not(i) == item["needs"]  # the card never decides


SET = fact("set pressure", "100", "psig")


def test_code_compares_each_limit():
    conventional = fact("valve type", "Conventional")
    over = {
        "PSV-A01": [fact("inlet pressure drop", "4", "psi")],  # 4 psi > 3% of 100 psig
        "PSV-A02": [
            conventional,
            fact("superimposed back pressure", "5", "psig"),
            fact("built-up back pressure", "7", "psig"),
        ],  # 5 + 7 = 12% >= 10%
    }
    for rule_id, extra in over.items():
        r = results([SET, *extra])[rule_id]
        assert r["status"] == "NON_COMPLIANT" and r["draft"] is True, rule_id
    ok = results(
        [
            SET,
            conventional,
            fact("inlet pressure drop", "2", "%"),
            fact("superimposed back pressure", "3", "psig"),
            fact("built-up back pressure", "4", "psig"),
        ]
    )
    assert ok["PSV-A01"]["status"] == ok["PSV-A02"]["status"] == "COMPLIANT"
    assert (
        results([SET])["PSV-A01"]["status"] == "MISSING_INFORMATION"
    )  # 9.7.2: the drop is stated on the sheet


def test_the_conventional_valve_check_does_not_apply_to_a_bellows_valve():
    r = results(
        [
            SET,
            fact("valve type", "Balanced bellows"),
            fact("superimposed back pressure", "50", "psig"),
        ]
    )
    assert r["PSV-A02"]["status"] == "NOT_APPLICABLE"


def _decided(rule_id, status="COMPLIANT"):
    return {
        "rule_id": rule_id,
        "status": status,
        "fact_id": "f1",
        "value": "2 %",
        "page": 2,
        "field": "Inlet pressure drop",
        "text": "an entry",
        "detail": "Inlet pressure drop 2 % (page 2) is at most 3%.",
    }


def test_the_calculator_never_turns_an_ai_draft_result_into_a_pass_or_fail():
    pages = {2: "Inlet pressure drop 2 %"}
    control = calc.checklist_lines(
        [{**_decided("PSV-24"), "field": "Set pressure"}],
        page_texts={2: "Set pressure 2 %"},
    )[0]
    assert control["verdict"] == calc.PASS  # an ordinary entry: the code decides
    assert (
        calc.checklist_lines([_decided("PSV-A01")], page_texts=pages) == []
    )  # a draft limit met: no line
    held = {**_decided("PSV-A01", "NEEDS_ENGINEER_REVIEW"), "rule_said": "COMPLIANT"}
    assert (
        calc.checklist_lines([held], page_texts=pages) == []
    )  # met, held by rule trust: no line either
    for status in ("NON_COMPLIANT", "MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"):
        line = calc.checklist_lines([_decided("PSV-A01", status)], page_texts=pages)[0]
        assert line["verdict"] == calc.QUERY and line["ai_draft"] is True, status
        assert (
            line["why"].startswith(calc.AI_DRAFT_WORDS)
            and line["compare"]["code_said"] == status
        )
        # the entry's own words are never shown as the book's quote
        assert (
            line["clause_quote"] == ""
            and line["check_words"] == "an entry"
            and line["quotes_checked"]["clause"] is False
        )
    assert (
        calc.checklist_lines([_decided("PSV-A02", "NOT_APPLICABLE")], page_texts=pages)
        == []
    )


def _sum(*parts):
    return results([SET, fact("valve type", "Conventional"), *parts])["PSV-A02"]


def test_5_1_1_compares_the_sum_of_the_two_back_pressures_never_one_part():
    sup, bu = "superimposed back pressure", "built-up back pressure"
    # each part alone is below 10%, the sum is not: the check must fail on the sum
    r = _sum(fact(sup, "6", "psig"), fact(bu, "6", "psig"))
    assert r["status"] == "NON_COMPLIANT" and "12.0%" in r["detail"]
    assert (
        _sum(fact(sup, "5", "psig"), fact(bu, "5", "psig"))["status"] == "NON_COMPLIANT"
    )  # 10% is not below 10%
    assert (
        _sum(fact(sup, "3", "psig"), fact(bu, "4", "%"))["status"] == "COMPLIANT"
    )  # a part stated as a percent
    # a part not given, marked by the contractor, or on no gauge basis: never a Pass, never taken as 0
    assert _sum(fact(sup, "3", "psig"))["status"] == "NEEDS_ENGINEER_REVIEW"
    marked = {
        **fact(bu, "By Contractor"),
        "raw_value": None,
        "is_blank": 1,
        "blank_marker": "By Contractor",
    }
    assert _sum(fact(sup, "3", "psig"), marked)["status"] == "MISSING_INFORMATION"
    assert (
        _sum(fact(sup, "3", "psi"), fact(bu, "4", "psig"))["status"]
        == "NEEDS_ENGINEER_REVIEW"
    )
