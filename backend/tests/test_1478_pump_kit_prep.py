"""#1478 pump kit PREPARATION: box list, draft rule cards, planted pump defects. Invented sheets, no model, no DB.

The proof of the kit waits for 2 real pump documents. What is tested here: the draft cards load only behind
`pump_kit_draft_enabled`, each card's passing and failing case behaves through the real `datasheet_checks.evaluate`,
planted pump defects are caught with 0 false passes, every card stays a draft that cannot decide, and switch off
changes nothing.
"""

from __future__ import annotations

import pytest

from app import card_trust, pump_kit, rule_cards
from app import datasheet_checks as dc
from app.config import settings

PUMP = "Centrifugal Pump"
PAGES = {1: "Rev Description Prepared Checked\n0 Issued for review"}


def _fact(name, value, unit=None, *, blank=None):
    printed = f"{value} {unit}".strip() if unit else value
    return {
        "id": f"f-{name}-{value}",
        "field_name": name,
        "field_label": name.capitalize(),
        "field_value": printed,
        "raw_value": None if blank else value,
        "raw_unit": unit,
        "normalized_value": None,
        "normalized_unit": None,
        "is_blank": 1 if blank else 0,
        "blank_marker": blank,
        "page": 1,
        "equipment_tag": None,
        "value_note": None,
    }


@pytest.fixture
def kit_on(monkeypatch):
    monkeypatch.setattr(settings, "pump_kit_draft_enabled", True)


def _kit_status(card, rows):
    """The card's own status on a whole invented sheet: the real evaluate on a one-item checklist."""
    rules = dc.load_rules()
    one = {
        **rules,
        "checklists": {PUMP: {"items": [card], "sign_off": {"status": "draft"}}},
    }
    facts = [_fact(n, v, u, blank=v if v in ("*", "TBA") else None) for n, v, u in rows]
    got = [
        r
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES, rules=one)
        if r.get("rule_id") == card["id"]
    ]
    return got[0]["status"] if got else None


def _by_id():
    return {c["id"]: c for c in pump_kit.cards()}


# ----------------------------------------------------------------- the data


def test_the_box_list_has_every_group_and_names_roles_the_checker_knows():
    boxes = pump_kit.boxes()
    assert {b["group"] for b in boxes} >= {
        "Performance",
        "Conditions",
        "Construction",
        "Connections",
        "Driver",
    }
    roles = dc.load_rules()["roles"]
    named = [b["role"] for b in boxes if b["role"]]
    assert named and all(r in roles for r in named)
    assert len({b["label"] for b in boxes}) == len(boxes)
    # a box with no role says so instead of pretending to be checked
    assert all(b.get("note") for b in boxes if not b["role"])


def test_every_card_is_a_draft_and_cites_a_standard_and_clause():
    for card in pump_kit.cards():
        assert card["draft"] is True
        assert card["source"]["standard"] and card["source"]["clause"]
    assert pump_kit.kit_report()["all_draft"] is True


def test_a_card_a_held_standard_requires_cites_it_with_a_clause_number_and_page():
    held = [c for c in pump_kit.cards() if not c.get("needs")]
    assert held
    for card in held:
        assert card["source"]["standard"] == "SAES-G-005"
        assert card_trust.has_clause_number(card)
        assert card["source"]["page"] > 0


def test_a_value_no_held_standard_requires_stays_draft_needs_a_standard():
    needy = [c for c in pump_kit.cards() if c.get("needs")]
    assert needy
    not_held = [c for c in needy if c["source"]["standard"] == "API 610"]
    wrong_clause = [c for c in needy if c["source"]["standard"] == "SAES-G-005"]
    assert len(not_held) == 11 and len(wrong_clause) == 4
    assert "API 610" in pump_kit._data()["standards_not_held"]
    for card in not_held:
        run = pump_kit.run_kit_card(card)
        assert run["status"] == "draft"
        assert run["why"] == "needs a standard we do not hold"
    # A-1440: a clause that only uses the value does not require stating it
    for card in wrong_clause:
        run = pump_kit.run_kit_card(card)
        assert run["status"] == "draft"
        assert "the cited clause does not" in run["why"]


def test_the_report_counts_tested_and_draft_needs_standard():
    report = pump_kit.kit_report()
    assert report["cards"] == 19
    assert report["tested"] == 4
    assert report["draft_needs_standard"] == 15
    assert report["draft_other"] == []
    assert report["boxes"] == len(pump_kit.boxes())


# ---------------------------------------------- each card: passing and failing case


@pytest.mark.parametrize(
    "card_id", [c["id"] for c in pump_kit.cards() if not c.get("needs")]
)
def test_each_held_card_passes_its_passing_and_failing_cases_through_the_real_code(
    card_id,
):
    run = pump_kit.run_kit_card(_by_id()[card_id])
    names = {r["case"] for r in run["runs"]}
    assert {"meets", "breaks", "unclear"} <= names
    assert all(r["passed"] for r in run["runs"]), run["runs"]
    assert run["status"] == "tested"


def test_a_wrong_expectation_in_a_card_case_is_reported_as_a_failed_case():
    card = dict(_by_id()["PMPD-04"])
    card["tests"] = [
        {
            "name": "meets",
            "facts": [["NPSH available", "4.5", "m"], ["NPSH required", "4", "m"]],
            "expect": "COMPLIANT",
        },
        *[t for t in card["tests"] if t["name"] != "meets"],
    ]
    run = pump_kit.run_kit_card(card)
    assert run["status"] == "draft" and run["why"] == "a case failed"


# --------------------------------------------------------- planted pump defects

BASE = [
    ("rated flow", "120", "m3/h"),
    ("NPSH available", "8", "m"),
    ("NPSH required", "4", "m"),
    ("absorbed power", "45", "kW"),
    ("seal type", "single mechanical seal", None),
    ("seal flush plan", "Plan 11", None),
    ("hydrotest pressure", "4500", "kPa"),
]


def _sheet(**changes):
    rows = {r[0].replace(" ", "_").lower(): r for r in BASE}
    for key, new in changes.items():
        if new is None:
            rows.pop(key, None)
        else:
            rows[key] = (rows[key][0], *new)
    return list(rows.values())


#: (what is planted, sheet, card that must not read COMPLIANT, statuses it may read)
PLANTED = [
    (
        "NPSHA only 0.5 m above NPSHR",
        _sheet(npsh_available=("4.5", "m")),
        "PMPD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "NPSHA equal to NPSHR",
        _sheet(npsh_available=("4", "m")),
        "PMPD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "NPSHA below NPSHR",
        _sheet(npsh_available=("2", "m")),
        "PMPD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "NPSHA in mm instead of m",
        _sheet(npsh_available=("4500", "mm")),
        "PMPD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "hydrotest below the floor",
        _sheet(hydrotest_pressure=("1500", "kPa")),
        "PMPD-08",
        {"NON_COMPLIANT"},
    ),
    (
        "hydrotest one unit under the floor",
        _sheet(hydrotest_pressure=("1723", "kPa")),
        "PMPD-08",
        {"NON_COMPLIANT"},
    ),
    ("rated flow missing", _sheet(rated_flow=None), "PMPD-01", {"MISSING_INFORMATION"}),
    ("NPSHA missing", _sheet(npsh_available=None), "PMPD-02", {"MISSING_INFORMATION"}),
    ("NPSHR missing", _sheet(npsh_required=None), "PMPD-03", {"MISSING_INFORMATION"}),
    (
        "NPSHA missing, margin rule",
        _sheet(npsh_available=None),
        "PMPD-04",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "NPSHR missing, margin rule",
        _sheet(npsh_required=None),
        "PMPD-04",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "absorbed power missing",
        _sheet(absorbed_power=None),
        "PMPD-05",
        {"MISSING_INFORMATION"},
    ),
    ("seal type missing", _sheet(seal_type=None), "PMPD-06", {"MISSING_INFORMATION"}),
    (
        "seal plan missing",
        _sheet(seal_flush_plan=None),
        "PMPD-07",
        {"MISSING_INFORMATION"},
    ),
    (
        "hydrotest not stated",
        _sheet(hydrotest_pressure=None),
        "PMPD-08",
        {"MISSING_INFORMATION"},
    ),
    (
        "seal type a placeholder",
        _sheet(seal_type=("*", None)),
        "PMPD-06",
        {"MISSING_INFORMATION"},
    ),
]

#: Traps: inside the limit or exactly at it, each must read COMPLIANT.
TRAPS = [
    ("NPSHA exactly 1 m above", _sheet(npsh_available=("5", "m")), "PMPD-04"),
    ("NPSHA far above", _sheet(npsh_available=("20", "m")), "PMPD-04"),
    (
        "hydrotest exactly at the floor",
        _sheet(hydrotest_pressure=("1724", "kPa")),
        "PMPD-08",
    ),
    (
        "hydrotest in bar above the floor",
        _sheet(hydrotest_pressure=("30", "bar")),
        "PMPD-08",
    ),
    ("clean sheet, rated flow", _sheet(), "PMPD-01"),
]


@pytest.mark.parametrize(
    "what,rows,card_id,allowed", PLANTED, ids=[p[0] for p in PLANTED]
)
def test_a_planted_pump_defect_is_caught_never_a_pass(what, rows, card_id, allowed):
    got = _kit_status(_by_id()[card_id], rows)
    assert got in allowed, (what, got)


@pytest.mark.parametrize("what,rows,card_id", TRAPS, ids=[t[0] for t in TRAPS])
def test_a_value_at_or_inside_the_limit_is_not_flagged(what, rows, card_id):
    assert _kit_status(_by_id()[card_id], rows) == "COMPLIANT", what


def test_the_planted_totals_every_defect_caught_zero_false_passes():
    caught = false_passes = 0
    for _what, rows, card_id, allowed in PLANTED:
        got = _kit_status(_by_id()[card_id], rows)
        caught += got in allowed
        false_passes += got == "COMPLIANT"
    assert (caught, false_passes) == (len(PLANTED), 0)
    assert len(PLANTED) >= 16


def test_the_clean_sheet_raises_no_fail_on_any_held_card():
    for card in pump_kit.cards():
        if card.get("needs"):
            continue
        assert _kit_status(card, BASE) == "COMPLIANT", card["id"]


# ------------------------------------------------- the switch and the live path


def test_switch_off_the_pump_checklist_is_the_committed_one():
    assert settings.pump_kit_draft_enabled is False
    items = dc.checklist_for(PUMP, dc.load_rules())["items"]
    assert len(items) == 17
    assert not [i for i in items if i["id"].startswith("PMPD")]
    assert pump_kit.loader_items(PUMP, items) == []


def test_switch_on_only_the_cards_nothing_committed_already_asks_are_added(kit_on):
    base_ids = {i["id"] for i in dc.load_rules()["checklists"][PUMP]["items"]}
    items = dc.checklist_for(PUMP, dc.load_rules())["items"]
    added = [i for i in items if i["id"] not in base_ids]
    assert {i["id"] for i in added} == {"PMPD-04", "PMPD-08"}
    assert all(i["draft"] and i["kit"] == "pump" for i in added)
    assert not [i for i in items if i.get("needs")]
    # no rule is asked twice
    keys = [
        (i["rule"]["kind"], i["rule"].get("field") or i["rule"].get("left"))
        for i in items
    ]
    assert len(keys) == len(set(keys))


def test_switch_on_other_equipment_types_are_unchanged(kit_on):
    rules = dc.load_rules()
    for key in ("Pressure Safety Valve", "Pressure Vessel", "Heat Exchanger"):
        assert pump_kit.loader_items(key, rules["checklists"][key]["items"]) == []


def _live(rows):
    facts = [_fact(n, v, u) for n, v, u in rows]
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES)
    }


def test_switch_off_a_low_npsh_margin_is_not_judged_at_all():
    assert "PMPD-04" not in _live(_sheet(npsh_available=("4.5", "m")))


def test_switch_on_a_low_npsh_margin_and_a_low_test_pressure_fail_on_a_whole_sheet(
    kit_on,
):
    out = _live(_sheet(npsh_available=("4.5", "m"), hydrotest_pressure=("1500", "kPa")))
    assert out["PMPD-04"]["rule_said"] == "NON_COMPLIANT"
    assert out["PMPD-08"]["rule_said"] == "NON_COMPLIANT"
    assert (
        out["PMPD-04"]["draft"] is True and out["PMPD-04"]["standard"] == "SAES-G-005"
    )
    assert out["PMPD-04"]["clause"] == "4.3.2"
    clean = _live(BASE)
    assert clean["PMPD-04"]["rule_said"] == "COMPLIANT"
    assert clean["PMPD-08"]["rule_said"] == "COMPLIANT"


def test_a_kit_card_never_decides_even_with_tested_cards_deciding(kit_on, monkeypatch):
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)
    for card in pump_kit.cards():
        assert card_trust.why_not(card["id"]) is not None
        assert card_trust.decides({"checklist": True, "rule_id": card["id"]}) is False
    assert PUMP not in card_trust.DECIDING_TYPES


def test_the_committed_checklists_and_their_card_report_are_untouched():
    report = rule_cards.report()
    assert report[PUMP]["cards"] == 17
    assert "PMPD-04" not in str(report)


# ------------------------------------------- held for the engineer, always


@pytest.mark.parametrize("auto_use", [False, True])
def test_a_kit_result_is_always_held_whatever_rule_auto_use_says(
    kit_on, monkeypatch, auto_use
):
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", auto_use)
    out = _live(_sheet(npsh_available=("4.5", "m"), hydrotest_pressure=("1723", "kPa")))
    for rule_id in ("PMPD-04", "PMPD-08"):
        row = rule_trust.label_check(out[rule_id])
        assert row["status"] == "NEEDS_ENGINEER_REVIEW", rule_id
        assert row["rule_said"] == "NON_COMPLIANT"
        assert row["detail"].startswith("The numbers read:")
        assert (
            "not at least" in row["detail"] or "not at least" in out[rule_id]["detail"]
        )
    clean = _live(BASE)
    for rule_id in ("PMPD-04", "PMPD-08"):
        row = rule_trust.label_check(clean[rule_id])
        assert (
            row["status"] == "NEEDS_ENGINEER_REVIEW" and row["rule_said"] == "COMPLIANT"
        )


def test_a_signed_off_pump_checklist_cannot_confirm_a_kit_card(kit_on, monkeypatch):
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    rules = dc.load_rules()
    rules["checklists"][PUMP]["sign_off"] = {"status": "signed"}
    facts = [_fact(n, v, u) for n, v, u in _sheet(npsh_available=("4.5", "m"))]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES, rules=rules)
    }
    assert res["PMPD-04"]["draft"] is True and res["PMPD-04"]["local"] is True
    assert rule_trust.check_label(res["PMPD-04"]) != rule_trust.ENGINEER_CONFIRMED
    assert rule_trust.label_check(res["PMPD-04"])["status"] == "NEEDS_ENGINEER_REVIEW"
    # a committed item of the same signed checklist is confirmed as before
    assert rule_trust.check_label(res["PMP-01"]) == rule_trust.ENGINEER_CONFIRMED


def test_a_kit_row_says_it_is_a_draft_with_unverified_clauses(kit_on):
    out = _live(_sheet(npsh_available=("4.5", "m")))
    assert pump_kit.KIT_WORDS in out["PMPD-04"]["text"]
    assert "not yet verified" in out["PMPD-04"]["text"]
    assert dc.DRAFT_MARK in out["PMPD-04"]["text"]
    assert pump_kit._data()["clauses_verified"] is False


def test_the_npsh_text_states_the_margin_and_the_cards_state_what_they_do_not_check():
    # MUST 2: the right-hand side is never printed without its margin
    one = {
        **dc.load_rules(),
        "checklists": {
            PUMP: {"items": [_by_id()["PMPD-04"]], "sign_off": {"status": "draft"}}
        },
    }
    facts = [_fact(n, v, u) for n, v, u in _sheet(npsh_available=("4.5", "m"))]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=PAGES, rules=one)
    }
    assert "plus the greater of 0% or 1 m" in res["PMPD-04"]["detail"]
    assert "not at least" in res["PMPD-04"]["detail"]
    assert "firewater" in _by_id()["PMPD-04"]["text"]
    assert "1.5 times shutoff" in _by_id()["PMPD-08"]["text"]


def test_a_relief_valve_margin_text_also_states_its_margin():
    sheet = [
        ("set pressure", "10", "barg"),
        ("operating pressure", "9.5", "barg"),
    ]
    facts = [_fact(n, v, u) for n, v, u in sheet]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(
            facts, equipment_type="Pressure Safety Valve", page_texts=PAGES
        )
    }
    assert "plus the greater of 10% or 100 kPa" in res["PSV-S03"]["detail"]


def test_a_percent_rule_text_is_unchanged():
    sheet = [("built up back pressure", "8", "%"), ("set pressure", "10", "barg")]
    facts = [
        _fact(n, v, u) for n, v, u in [*sheet, ("valve type", "conventional", None)]
    ]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(
            facts, equipment_type="Pressure Safety Valve", page_texts=PAGES
        )
    }
    assert "10% of" in res["PSV-29"]["detail"]


def test_the_standards_own_unit_for_the_test_pressure_is_not_a_fail():
    for value, unit, ok in (
        ("250", "psi", True),
        ("1724", "kPa", True),
        ("1723", "kPa", False),
    ):
        got = _kit_status(_by_id()["PMPD-08"], _sheet(hydrotest_pressure=(value, unit)))
        assert got == ("COMPLIANT" if ok else "NON_COMPLIANT"), (value, unit)
