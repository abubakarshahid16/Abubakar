"""#1480 vessel kit PREPARATION (parked kit): box list, draft rule cards, planted vessel defects. Invented sheets, no model, no DB.

The proof of the kit waits for 2 real vessel documents. What is tested here: the draft cards load only behind
`vessel_kit_draft_enabled`, each card's passing, failing and at-the-limit case behaves through the real
`datasheet_checks.evaluate`, planted vessel defects are caught with 0 false passes, every kit row is held for the
engineer whatever `rule_auto_use_enabled` says, switch off changes nothing, and the shared kit mechanism leaves the
pump kit as it was.
"""

from __future__ import annotations

import pytest

from app import card_trust, kit_core, pump_kit, rule_cards, vessel_kit
from app import datasheet_checks as dc
from app.config import settings

VESSEL = "Pressure Vessel"
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
    monkeypatch.setattr(settings, "vessel_kit_draft_enabled", True)


def _by_id():
    return {c["id"]: c for c in vessel_kit.cards()}


def _kit_status(card, rows):
    """The card's own status on a whole invented sheet: the real evaluate on a one-item checklist."""
    rules = dc.load_rules()
    one = {
        **rules,
        "checklists": {VESSEL: {"items": [card], "sign_off": {"status": "draft"}}},
    }
    facts = [_fact(n, v, u, blank=v if v in ("*", "TBA") else None) for n, v, u in rows]
    got = [
        r
        for r in dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES, rules=one)
        if r.get("rule_id") == card["id"]
    ]
    return got[0]["status"] if got else None


def _live(rows):
    facts = [_fact(n, v, u) for n, v, u in rows]
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES)
    }


# ----------------------------------------------------------------- the data


def test_the_box_list_has_every_group_and_names_roles_the_checker_knows():
    boxes = vessel_kit.boxes()
    assert {b["group"] for b in boxes} >= {
        "Design basis",
        "Construction",
        "Dimensions",
        "Connections",
        "Protection",
        "Loads",
    }
    roles = dc.load_rules()["roles"]
    named = [b["role"] for b in boxes if b["role"]]
    assert named and all(r in roles for r in named)
    assert len({b["label"] for b in boxes}) == len(boxes)
    # a box with no role says so instead of pretending to be checked
    assert all(b.get("note") for b in boxes if not b["role"])
    # every vessel box the committed checklist already asks for is on the list (one canonical name per field)
    committed = {
        i["rule"]["field"] for i in dc.load_rules()["checklists"][VESSEL]["items"]
    }
    assert committed <= set(named)


def test_every_card_is_a_draft_and_cites_a_standard_and_clause():
    for card in vessel_kit.cards():
        assert card["draft"] is True
        assert card["source"]["standard"] and card["source"]["clause"]
    assert vessel_kit.kit_report()["all_draft"] is True
    assert vessel_kit._data()["clauses_verified"] is False


def test_a_card_a_held_standard_requires_cites_it_with_a_clause_number_and_page():
    held = [c for c in vessel_kit.cards() if not c.get("needs")]
    assert held
    for card in held:
        assert card["source"]["standard"] == "SAES-D-001"
        assert card_trust.has_clause_number(card)
        assert card["source"]["page"] > 0


def test_no_card_cites_an_asme_clause_as_verified():
    # ASME VIII-1 is held, but 0 of its 4,073 stored rules carry ASME's own clause numbers
    asme = [c for c in vessel_kit.cards() if "ASME" in c["source"]["standard"]]
    assert len(asme) == 2
    for card in asme:
        assert card.get("needs")
        assert not card_trust.has_clause_number(card)
        run = vessel_kit.run_kit_card(card)
        assert run["status"] == "draft" and run["why"].startswith("needs ")
    assert "ASME BPVC VIII-1" not in vessel_kit._data()["standards_held"]


def test_a_value_no_held_clause_requires_stays_draft_needs_a_standard():
    needy = [c for c in vessel_kit.cards() if c.get("needs")]
    assert len(needy) == 6
    # A-1440: a clause that only uses the value does not require stating it
    wrong_clause = [c for c in needy if c["source"]["standard"] == "SAES-D-001"]
    assert len(wrong_clause) == 4
    for card in wrong_clause:
        run = vessel_kit.run_kit_card(card)
        assert run["status"] == "draft"
        assert "the cited clause does not" in run["why"]


def test_the_report_counts_tested_and_draft_needs_standard():
    report = vessel_kit.kit_report()
    assert report["cards"] == 11
    assert report["tested"] == 5
    assert report["draft_needs_standard"] == 6
    assert report["draft_other"] == []
    assert report["boxes"] == len(vessel_kit.boxes()) == 31


# ---------------------------------------------- each card: passing and failing case


@pytest.mark.parametrize(
    "card_id", [c["id"] for c in vessel_kit.cards() if not c.get("needs")]
)
def test_each_held_card_passes_its_cases_through_the_real_code(card_id):
    run = vessel_kit.run_kit_card(_by_id()[card_id])
    names = {r["case"] for r in run["runs"]}
    assert {"meets", "breaks", "unclear"} <= names
    assert all(r["passed"] for r in run["runs"]), run["runs"]
    assert run["status"] == "tested"


def test_the_two_limit_cards_have_an_at_the_limit_and_a_unit_case():
    for card_id in ("VSLD-04", "VSLD-05"):
        names = {t["name"] for t in _by_id()[card_id]["tests"]}
        assert "at the limit" in names
    names = {t["name"] for t in _by_id()["VSLD-05"]["tests"]}
    assert {
        "a different unit above the limit",
        "a different unit below the limit",
    } <= names


def test_a_wrong_expectation_in_a_card_case_is_reported_as_a_failed_case():
    card = dict(_by_id()["VSLD-05"])
    card["tests"] = [
        {
            "name": "meets",
            "facts": [
                ["design pressure", "10.4", "barg"],
                ["maximum operating pressure", "10", "barg"],
            ],
            "expect": "COMPLIANT",
        },
        *[t for t in card["tests"] if t["name"] != "meets"],
    ]
    run = vessel_kit.run_kit_card(card)
    assert run["status"] == "draft" and run["why"] == "a case failed"


# --------------------------------------------------------- planted vessel defects

BASE = [
    ("design pressure", "11", "barg"),
    ("maximum operating pressure", "10", "barg"),
    ("design code", "ASME VIII Div 1, 2023", None),
    ("minimum design metal temperature", "-29", "C"),
    ("joint efficiency", "1.0", None),
    ("corrosion allowance", "3", "mm"),
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
        "design pressure only 4% over the operating pressure",
        _sheet(design_pressure=("10.4", "barg")),
        "VSLD-05",
        {"NON_COMPLIANT"},
    ),
    (
        "design pressure equal to the operating pressure",
        _sheet(design_pressure=("10", "barg")),
        "VSLD-05",
        {"NON_COMPLIANT"},
    ),
    (
        "design pressure below the operating pressure",
        _sheet(design_pressure=("9", "barg")),
        "VSLD-05",
        {"NON_COMPLIANT"},
    ),
    (
        "design pressure just under the limit, in MPa against kPa",
        _sheet(
            design_pressure=("1.15", "MPa"), maximum_operating_pressure=("1100", "kPa")
        ),
        "VSLD-05",
        {"NON_COMPLIANT"},
    ),
    (
        "joint efficiency 0.7",
        _sheet(joint_efficiency=("0.7", None)),
        "VSLD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "joint efficiency one step under the floor",
        _sheet(joint_efficiency=("0.849", None)),
        "VSLD-04",
        {"NON_COMPLIANT"},
    ),
    (
        "joint efficiency printed as a bare 70",
        _sheet(joint_efficiency=("70", None)),
        "VSLD-04",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "joint efficiency printed as 70 %",
        _sheet(joint_efficiency=("70", "%")),
        "VSLD-04",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "joint efficiency of 0 (an entry error)",
        _sheet(joint_efficiency=("0", None)),
        "VSLD-04",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "design pressure missing",
        _sheet(design_pressure=None),
        "VSLD-01",
        {"MISSING_INFORMATION"},
    ),
    (
        "design code missing",
        _sheet(design_code=None),
        "VSLD-02",
        {"MISSING_INFORMATION"},
    ),
    (
        "MDMT missing",
        _sheet(minimum_design_metal_temperature=None),
        "VSLD-03",
        {"MISSING_INFORMATION"},
    ),
    (
        "joint efficiency missing",
        _sheet(joint_efficiency=None),
        "VSLD-04",
        {"MISSING_INFORMATION"},
    ),
    (
        "design pressure missing, margin rule",
        _sheet(design_pressure=None),
        "VSLD-05",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "operating pressure missing, margin rule",
        _sheet(maximum_operating_pressure=None),
        "VSLD-05",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "design code a placeholder",
        _sheet(design_code=("*", None)),
        "VSLD-02",
        {"MISSING_INFORMATION"},
    ),
    (
        "MDMT marked TBA",
        _sheet(minimum_design_metal_temperature=("TBA", None)),
        "VSLD-03",
        {"MISSING_INFORMATION"},
    ),
]

#: Traps: inside the limit or exactly at it, each must read COMPLIANT.
TRAPS = [
    (
        "design pressure exactly 5% over",
        _sheet(design_pressure=("10.5", "barg")),
        "VSLD-05",
    ),
    ("design pressure far above", _sheet(design_pressure=("20", "barg")), "VSLD-05"),
    (
        "design pressure above the limit, in MPa against kPa",
        _sheet(
            design_pressure=("1.2", "MPa"), maximum_operating_pressure=("1100", "kPa")
        ),
        "VSLD-05",
    ),
    (
        "joint efficiency exactly 0.85",
        _sheet(joint_efficiency=("0.85", None)),
        "VSLD-04",
    ),
    ("joint efficiency 1.0", _sheet(), "VSLD-04"),
    ("clean sheet, design pressure stated", _sheet(), "VSLD-01"),
]


@pytest.mark.parametrize(
    "what,rows,card_id,allowed", PLANTED, ids=[p[0] for p in PLANTED]
)
def test_a_planted_vessel_defect_is_caught_never_a_pass(what, rows, card_id, allowed):
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
    for card in vessel_kit.cards():
        if card.get("needs"):
            continue
        assert _kit_status(card, BASE) == "COMPLIANT", card["id"]


def test_a_card_bound_is_the_cards_own_and_the_committed_role_is_untouched():
    # a bare 70 is still "stated" for the committed row, switch off: nothing changed there
    assert "plausible" not in dc.load_rules()["roles"]["joint_efficiency"]
    out = _live(_sheet(joint_efficiency=("70", None)))
    assert out["VSL-13"]["status"] == "COMPLIANT"
    assert "VSLD-04" not in out


# ------------------------------------------------- the switch and the live path


def test_the_switch_is_off_by_default_and_documented():
    from pathlib import Path

    from . import env_isolation

    assert settings.vessel_kit_draft_enabled is False
    assert env_isolation.EGRESS_SAFE["vessel_kit_draft_enabled"] is False
    flags = (Path(__file__).resolve().parents[2] / "docs" / "flags.md").read_text(
        encoding="utf-8"
    )
    assert "`vessel_kit_draft_enabled` | `False`" in flags


def test_switch_off_the_vessel_checklist_is_the_committed_one():
    committed = dc.load_rules()["checklists"][VESSEL]["items"]
    items = dc.checklist_for(VESSEL, dc.load_rules())["items"]
    assert len(items) == len(committed) == 18
    assert not [i for i in items if i["id"].startswith("VSLD")]
    assert vessel_kit.loader_items(VESSEL, items) == []


def test_switch_on_only_the_cards_nothing_committed_already_asks_are_added(kit_on):
    base_ids = {i["id"] for i in dc.load_rules()["checklists"][VESSEL]["items"]}
    items = dc.checklist_for(VESSEL, dc.load_rules())["items"]
    added = [i for i in items if i["id"] not in base_ids]
    assert {i["id"] for i in added} == {"VSLD-04", "VSLD-05"}
    assert all(i["draft"] and i["kit"] == "vessel" for i in added)
    assert not [i for i in items if i.get("needs")]
    keys = [
        (
            i["rule"]["kind"],
            i["rule"].get("field") or i["rule"].get("left"),
            i["rule"].get("right"),
        )
        for i in items
    ]
    assert len(keys) == len(set(keys))


def test_switch_on_other_equipment_types_are_unchanged(kit_on):
    rules = dc.load_rules()
    for key in ("Pressure Safety Valve", "Heat Exchanger", PUMP):
        assert vessel_kit.loader_items(key, rules["checklists"][key]["items"]) == []
        assert (
            kit_core.with_kit(key, rules["checklists"][key]["items"])
            == rules["checklists"][key]["items"]
        )


def test_switch_off_a_low_design_pressure_margin_is_not_judged_at_all():
    assert "VSLD-05" not in _live(_sheet(design_pressure=("10.4", "barg")))


def test_switch_on_a_low_margin_and_a_low_joint_efficiency_fail_on_a_whole_sheet(
    kit_on,
):
    out = _live(
        _sheet(design_pressure=("10.4", "barg"), joint_efficiency=("0.7", None))
    )
    assert out["VSLD-05"]["rule_said"] == "NON_COMPLIANT"
    assert out["VSLD-04"]["rule_said"] == "NON_COMPLIANT"
    assert out["VSLD-05"]["draft"] is True
    assert out["VSLD-05"]["standard"] == "SAES-D-001"
    assert out["VSLD-05"]["clause"] == "6.2.3"
    clean = _live(BASE)
    assert clean["VSLD-05"]["rule_said"] == "COMPLIANT"
    assert clean["VSLD-04"]["rule_said"] == "COMPLIANT"


def test_a_kit_card_never_decides_even_with_tested_cards_deciding(kit_on, monkeypatch):
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)
    for card in vessel_kit.cards():
        assert card_trust.why_not(card["id"]) is not None
        assert card_trust.decides({"checklist": True, "rule_id": card["id"]}) is False
    assert VESSEL not in card_trust.DECIDING_TYPES


def test_the_committed_checklists_and_their_card_report_are_untouched():
    report = rule_cards.report()
    assert report[VESSEL]["cards"] == 18
    assert "VSLD" not in str(report)


# ------------------------------------------- held for the engineer, always


@pytest.mark.parametrize("auto_use", [False, True])
def test_a_kit_result_is_always_held_whatever_rule_auto_use_says(
    kit_on, monkeypatch, auto_use
):
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", auto_use)
    out = _live(
        _sheet(design_pressure=("10.4", "barg"), joint_efficiency=("0.7", None))
    )
    for rule_id in ("VSLD-04", "VSLD-05"):
        row = rule_trust.label_check(out[rule_id])
        assert row["status"] == "NEEDS_ENGINEER_REVIEW", rule_id
        assert row["rule_said"] == "NON_COMPLIANT"
        assert row["detail"].startswith("The numbers read:")
    clean = _live(BASE)
    for rule_id in ("VSLD-04", "VSLD-05"):
        row = rule_trust.label_check(clean[rule_id])
        assert (
            row["status"] == "NEEDS_ENGINEER_REVIEW" and row["rule_said"] == "COMPLIANT"
        )


def test_a_signed_off_vessel_checklist_cannot_confirm_a_kit_card(kit_on, monkeypatch):
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    rules = dc.load_rules()
    rules["checklists"][VESSEL]["sign_off"] = {"status": "signed"}
    facts = [_fact(n, v, u) for n, v, u in _sheet(design_pressure=("10.4", "barg"))]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(
            facts, equipment_type=VESSEL, page_texts=PAGES, rules=rules
        )
    }
    assert res["VSLD-05"]["draft"] is True and res["VSLD-05"]["local"] is True
    assert rule_trust.check_label(res["VSLD-05"]) != rule_trust.ENGINEER_CONFIRMED
    assert rule_trust.label_check(res["VSLD-05"])["status"] == "NEEDS_ENGINEER_REVIEW"
    # a committed item of the same signed checklist is confirmed as before
    assert rule_trust.check_label(res["VSL-01"]) == rule_trust.ENGINEER_CONFIRMED


def test_a_kit_row_says_it_is_a_vessel_draft_with_unverified_clauses(kit_on):
    out = _live(_sheet(design_pressure=("10.4", "barg")))
    assert vessel_kit.KIT_WORDS in out["VSLD-05"]["text"]
    assert "not yet verified" in out["VSLD-05"]["text"]
    assert "pump" not in out["VSLD-05"]["text"]
    assert dc.DRAFT_MARK in out["VSLD-05"]["text"]


def test_the_margin_text_states_the_factor_in_full_and_what_is_not_checked():
    one = {
        **dc.load_rules(),
        "checklists": {
            VESSEL: {"items": [_by_id()["VSLD-05"]], "sign_off": {"status": "draft"}}
        },
    }
    facts = [_fact(n, v, u) for n, v, u in _sheet(design_pressure=("10.4", "barg"))]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES, rules=one)
    }
    assert "105% of" in res["VSLD-05"]["detail"]
    assert (
        "not at least" not in res["VSLD-05"]["detail"]
        or "105%" in res["VSLD-05"]["detail"]
    )
    text = _by_id()["VSLD-05"]["text"]
    assert "1.05 times" in text and "1.1" in text and "6,900 kPa" in text
    assert "normal and not the maximum" in text
    assert "percentage" in _by_id()["VSLD-04"]["text"]


# ------------------------------------------- the shared mechanism, pump unchanged


def test_the_pump_kit_is_what_it_was_through_the_shared_mechanism():
    assert pump_kit.KIT_WORDS == (
        "DRAFT pump kit card: the clause number is as stored in the library and "
        "not yet verified by an engineer"
    )
    report = pump_kit.kit_report()
    assert (report["cards"], report["tested"], report["draft_needs_standard"]) == (
        19,
        4,
        15,
    )
    assert [k.name for k in kit_core.KITS] == ["pump", "vessel"]
    assert pump_kit.rows is kit_core.rows and pump_kit.held is kit_core.held


def test_both_switches_on_each_kit_adds_only_its_own_cards(monkeypatch):
    monkeypatch.setattr(settings, "vessel_kit_draft_enabled", True)
    monkeypatch.setattr(settings, "pump_kit_draft_enabled", True)
    rules = dc.load_rules()
    pump_ids = {i["id"] for i in dc.checklist_for(PUMP, rules)["items"]}
    vessel_ids = {i["id"] for i in dc.checklist_for(VESSEL, rules)["items"]}
    assert {"PMPD-04", "PMPD-08"} <= pump_ids and not any(
        i.startswith("VSLD") for i in pump_ids
    )
    assert {"VSLD-04", "VSLD-05"} <= vessel_ids and not any(
        i.startswith("PMPD") for i in vessel_ids
    )


def test_a_pump_row_is_held_with_the_pump_words_and_a_vessel_row_with_the_vessel_words(
    monkeypatch,
):
    monkeypatch.setattr(settings, "vessel_kit_draft_enabled", True)
    monkeypatch.setattr(settings, "pump_kit_draft_enabled", True)
    result = {"status": "COMPLIANT", "text": "t", "detail": "d"}
    pump = kit_core.held(result, {"kit": "pump"})
    vessel = kit_core.held(result, {"kit": "vessel"})
    assert pump_kit.KIT_WORDS in pump["text"] and vessel_kit.KIT_WORDS in vessel["text"]
    assert pump["kit"] == "pump" and vessel["kit"] == "vessel"
    assert pump["status"] == vessel["status"] == "NEEDS_ENGINEER_REVIEW"
    assert kit_core.held(result, {}) is result
