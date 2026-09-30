"""One value, one fact: the AI gate keeps a value to ONE quantity and moves the
conditions into `qualifier` (2026-09-30, from the ds07 measurement, where the
local reader returned whole sentences as values)."""

from __future__ import annotations

import json

from app import claude_datasheet as cd


def _one(value, unit=None):
    return cd.atomise([{"field": "Delivery", "value": value, "unit": unit,
                        "quote": "x", "kind": "offered"}])


def test_a_quantity_followed_by_words_keeps_the_words_as_a_qualifier():
    [p] = _one("16 weeks from purchase order, ex works")
    assert (p["value"], p["unit"]) == ("16", "weeks")
    assert p["qualifier"] == "from purchase order, ex works"


def test_a_quantity_with_a_unit_the_model_gave_keeps_that_unit():
    [p] = _one("6 in, full bore", unit="in")
    assert (p["value"], p["unit"], p["qualifier"]) == ("6", "in", "full bore")


def test_two_conditions_become_two_facts_not_one_muddled_value():
    facts = _one("18 months from delivery or 12 months from start-up")
    assert [(f["value"], f["unit"], f["qualifier"]) for f in facts] == [
        ("18", "months", "from delivery"), ("12", "months", "from start-up")]


def test_a_note_reference_is_not_a_condition():
    [p] = _one("12.5 barg (note 3)")
    assert p["value"] == "12.5" and p["qualifier"] is None


def test_values_that_are_not_one_quantity_plus_words_are_left_alone():
    for raw in ("10-20 bar", "0.5 to 2 bar", "2nd Stage", "153 barg",
                "forged carbon steel to ASTM A105", "ASME Class 600", "Yes"):
        [p] = _one(raw)
        assert p["value"] == raw and p.get("qualifier") is None, raw


def test_a_unit_the_system_does_not_know_is_never_split():
    [p] = _one("7 zorgs from order")
    assert p["value"] == "7 zorgs from order"


def test_atomise_is_idempotent():
    once = _one("16 weeks from purchase order")
    assert cd.atomise(once) == once


def test_the_gate_keeps_the_quote_as_evidence_for_each_piece():
    page = "8. Warranty: 18 months from delivery or 12 months from start-up."
    out = cd.accept([{"field": "Warranty", "unit": None, "kind": "offered",
                      "value": "18 months from delivery or 12 months from start-up",
                      "quote": "8. Warranty: 18 months from delivery or 12 months from start-up."}], page)
    assert [(a["value"], a["unit"], a["qualifier"]) for a in out["accepted"]] == [
        ("18", "months", "from delivery"), ("12", "months", "from start-up")]
    assert out["rejected"] == []


def test_parse_keeps_the_qualifier_the_model_gave():
    raw = json.dumps({"facts": [{"field": "Delivery", "value": "16", "unit": "weeks",
                                 "qualifier": "ex works", "quote": "Delivery: 16 weeks ex works",
                                 "kind": "offered"}]})
    [p], err = cd.parse_response(raw)
    assert err is None and p["qualifier"] == "ex works"


def test_read_page_agrees_when_the_two_readings_differ_only_in_wording():
    page = "7. Delivery: 16 weeks from purchase order, ex works."
    quote = "7. Delivery: 16 weeks from purchase order, ex works."

    def first(prompt):
        return json.dumps({"facts": [{"field": "Delivery", "unit": None, "kind": "offered",
                                      "value": "16 weeks from purchase order, ex works", "quote": quote}]})

    def second(prompt):
        return json.dumps({"facts": [{"field": "Delivery", "unit": "weeks", "kind": "offered",
                                      "value": "16", "qualifier": "ex works", "quote": quote}]})

    out = cd.read_page(page, 1, [], first, second_call=second)
    assert [(a["value"], a["unit"]) for a in out["accepted"]] == [("16", "weeks")]


def test_the_real_model_answers_seen_on_the_made_up_valve_sheet_come_out_clean():
    """Replays what the local model really returned for the made-up free-text
    valve sheet (measured 2026-09-30): whole sentences as values, the same in
    both runs. The gate must turn them into one quantity each."""
    rows = [
        ("Nominal size", "6 in, full bore", "1. Nominal size: 6 in, full bore."),
        ("Delivery", "16 weeks from purchase order, ex works",
         "7. Delivery: 16 weeks from purchase order, ex works."),
        ("Warranty", "18 months from delivery or 12 months from start-up",
         "8. Warranty: 18 months from delivery or 12 months from start-up."),
    ]
    page = "\n".join(q for _f, _v, q in rows)
    raw = json.dumps({"facts": [{"field": f, "value": v, "unit": None, "quote": q,
                                 "kind": "offered"} for f, v, q in rows]})
    out = cd.read_page(page, 1, [], lambda prompt: raw)
    got = [(a["field"], a["value"], a["unit"], a.get("qualifier")) for a in out["accepted"]]
    assert got == [
        ("Nominal size", "6", "in", "full bore"),
        ("Delivery", "16", "weeks", "from purchase order, ex works"),
        ("Warranty", "18", "months", "from delivery"),
        ("Warranty", "12", "months", "from start-up"),
    ]
    assert out["rejected"] == []
