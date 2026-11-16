"""Order 14, lane A: the valve numbers of SAES-J-600 (inlet drop 3%, conventional valve under 10% back pressure, API 526 orifice
D to T, form SA-8020-611) are compared by CODE in the checklist data, marked "AI draft, engineer to confirm", and never a Pass or
Fail: the checklist holds each result for the engineer with the numbers, and the calculator's line is a Query. Invented values only.
"""

from __future__ import annotations

from app import agent_review_calculator as calc
from app import datasheet_checks as dc

PSV = "Pressure Safety Valve"
DRAFTS = ("PSV-A01", "PSV-A02", "PSV-A03", "PSV-A04", "PSV-A05")


def fact(name, value, unit=None, *, label=None, page=2):
    return {"id": f"f-{name}-{value}", "field_name": name, "field_label": label or name.capitalize(),
            "field_value": f"{value} {unit}".strip() if unit else value, "raw_value": value, "raw_unit": unit,
            "normalized_value": None, "normalized_unit": None, "is_blank": 0, "blank_marker": None,
            "value_note": None, "page": page, "equipment_tag": None}


def results(facts):
    return {r["rule_id"]: r for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"}) if r.get("checklist")}


def test_each_ai_draft_item_cites_a_page_of_saes_j_600_and_says_it_is_a_draft():
    items = {i["id"]: i for i in dc.checklist_for(PSV, dc.load_rules())["items"]}
    assert set(DRAFTS) <= calc.ai_draft_ids()
    for i in DRAFTS:
        item = items[i]
        assert item["source"]["standard"] == "SAES-J-600" and item["source"]["clause"] and item["source"]["page"] >= 1
        assert calc.AI_DRAFT_WORDS in item["text"] and item["kit"] and item["needs"]


SET = fact("set pressure", "100", "psig")


def test_code_compares_each_limit_and_holds_it_for_the_engineer():
    conventional = fact("valve type", "Conventional")
    cases = {
        "PSV-A01": [fact("inlet pressure drop", "4", "psi")],          # 4 psi > 3% of 100 psig
        "PSV-A02": [conventional, fact("superimposed back pressure", "15", "psig")],  # 15% >= 10%
        "PSV-A03": [fact("orifice area", "0.05", "in2")],               # below D, 0.110 in2
        "PSV-A04": [fact("orifice area", "30", "in2")],                 # above T, 26.00 in2
        "PSV-A05": [conventional, fact("form no", "SA-8020-612")],      # the pilot valve's form
    }
    for rule_id, extra in cases.items():
        r = results([SET, *extra])[rule_id]
        assert r["status"] == "NEEDS_ENGINEER_REVIEW" and r["rule_said"] == "NON_COMPLIANT", rule_id
        assert r["detail"].startswith("The numbers read:"), rule_id
    ok = results([SET, fact("inlet pressure drop", "2", "%"), fact("orifice area", "0.503", "in2")])
    assert ok["PSV-A01"]["rule_said"] == ok["PSV-A03"]["rule_said"] == "COMPLIANT"
    assert ok["PSV-A01"]["status"] == ok["PSV-A03"]["status"] == "NEEDS_ENGINEER_REVIEW"


def test_the_conventional_valve_check_does_not_apply_to_a_bellows_valve():
    r = results([SET, fact("valve type", "Balanced bellows"), fact("superimposed back pressure", "50", "psig")])
    assert r["PSV-A02"]["status"] == "NOT_APPLICABLE"


def _decided(rule_id):
    """A result as if the check had decided (the data's hold removed): only the calculator stands between it and a verdict."""
    return {"rule_id": rule_id, "status": "COMPLIANT", "fact_id": "f1", "value": "0.503 in2", "page": 2,
            "field": "Orifice area", "text": "an entry", "detail": "Orifice area 0.503 in2 (page 2) is at least 0.11 in2."}


def test_the_calculator_never_turns_an_ai_draft_result_into_a_pass_or_fail():
    pages = {2: "Orifice area 0.503 in2"}
    control = calc.checklist_lines([_decided("PSV-24")], page_texts=pages)[0]
    assert control["verdict"] == calc.PASS                         # an ordinary entry: the code decides
    line = calc.checklist_lines([_decided("PSV-A03")], page_texts=pages)[0]
    assert line["verdict"] == calc.QUERY and line["ai_draft"] is True
    assert line["why"].startswith(calc.AI_DRAFT_WORDS) and line["compare"]["code_said"] == "COMPLIANT"
    for status in ("NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW", "MISSING_INFORMATION"):
        held = calc.checklist_lines([{**_decided("PSV-A03"), "status": status}], page_texts=pages)[0]
        assert held["verdict"] == calc.QUERY and held["why"].startswith(calc.AI_DRAFT_WORDS)
    assert calc.checklist_lines([{**_decided("PSV-A02"), "status": "NOT_APPLICABLE"}], page_texts=pages) == []
