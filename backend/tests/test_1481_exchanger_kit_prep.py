"""#1481 heat exchanger kit PREPARATION (parked kit): box list, draft rule cards, planted exchanger defects. Invented sheets, no model, no DB.

The proof of the kit waits for 2 real exchanger documents. What is tested here: the draft cards load only behind
`exchanger_kit_draft_enabled`, each card's passing, failing and at-the-limit case behaves through the real
`datasheet_checks.evaluate`, planted exchanger defects are caught with 0 false passes, every kit row is held for the
engineer whatever `rule_auto_use_enabled` says, switch off changes nothing, and the other kits are as they were.
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import (
    exchanger_kit,
    kit_core,
    pump_kit,
    question_card,
    rule_cards,
    rule_trust,
    vessel_kit,
)
from app.config import settings

HEX = "Heat Exchanger"
VESSEL = "Pressure Vessel"
PAGES = {1: "Rev Description Prepared Checked\n0 Issued for review"}
HELD_IDS = [f"EXHD-{n:02d}" for n in range(1, 12)]
NEEDS_IDS = [f"EXHD-{n:02d}" for n in range(12, 18)]


def _fact(name, value, unit=None, *, blank=None):
    printed = f"{value} {unit}".strip() if unit else value
    return {
        "id": f"f-{name}-{value}-{unit}",
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
    monkeypatch.setattr(settings, "exchanger_kit_draft_enabled", True)


def _by_id():
    return {c["id"]: c for c in exchanger_kit.cards()}


def _kit_status(card, rows):
    """The card's own status on a whole invented sheet: the real evaluate on a one-item checklist."""
    rules = dc.load_rules()
    one = {
        **rules,
        "checklists": {HEX: {"items": [card], "sign_off": {"status": "draft"}}},
    }
    facts = [_fact(n, v, u, blank=v if v in ("*", "TBA") else None) for n, v, u in rows]
    got = [
        r
        for r in dc.evaluate(facts, equipment_type=HEX, page_texts=PAGES, rules=one)
        if r.get("rule_id") == card["id"]
    ]
    return got[0]["status"] if got else None


def _live(rows):
    facts = [_fact(n, v, u) for n, v, u in rows]
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=HEX, page_texts=PAGES)
    }


# ----------------------------------------------------------------- the data


def test_the_box_list_has_every_group_and_names_roles_the_checker_knows():
    boxes = exchanger_kit.boxes()
    assert {b["group"] for b in boxes} == {
        "Design basis",
        "Tubes",
        "Shell and heads",
        "Thermal and hydraulic",
        "Connections and loads",
    }
    roles = dc.load_rules()["roles"]
    named = [b["role"] for b in boxes if b["role"]]
    assert named and all(r in roles for r in named)
    assert len({b["label"] for b in boxes}) == len(boxes)
    assert len(set(named)) == len(named)
    # a box with no role says so instead of pretending to be checked
    assert all(b.get("note") for b in boxes if not b["role"])
    # every exchanger box the committed checklist already asks for is on the list (one canonical name per field)
    committed = {
        i["rule"]["field"] for i in dc.load_rules()["checklists"][HEX]["items"]
    }
    assert committed <= set(named)


def test_every_card_is_a_draft_and_cites_a_standard_and_clause():
    for card in exchanger_kit.cards():
        assert card["draft"] is True
        assert card["source"]["standard"] and card["source"]["clause"]
    assert exchanger_kit.kit_report()["all_draft"] is True
    assert exchanger_kit._data()["clauses_verified"] is False


def test_a_card_a_held_standard_requires_cites_it_with_a_clause_number_and_page():
    held = [c for c in exchanger_kit.cards() if not c.get("needs")]
    assert [c["id"] for c in held] == HELD_IDS
    for card in held:
        assert card["source"]["standard"] == "SAES-E-004"
        assert kit_core.has_clause_number(card)
        assert card["source"]["page"] > 0


def test_no_card_cites_a_standard_the_library_does_not_hold():
    data = exchanger_kit._data()
    assert data["standards_held"] == ["SAES-E-004"]
    assert {"TEMA", "API 660", "API 661"} <= set(data["standards_not_held"])
    for card in exchanger_kit.cards():
        assert card["source"]["standard"] == "SAES-E-004"
    # the committed checklist names them, the kit does not
    assert (
        "TEMA" in dc.load_rules()["checklists"][HEX]["items"][0]["source"]["standard"]
    )


def test_a_value_no_held_clause_requires_stays_draft_needs_a_standard():
    needy = [c for c in exchanger_kit.cards() if c.get("needs")]
    assert [c["id"] for c in needy] == NEEDS_IDS
    # A-1440: a clause that only uses the value does not require stating it
    for card in needy:
        assert card["source"]["standard"] == "SAES-E-004"
        run = exchanger_kit.run_kit_card(card)
        assert run["status"] == "draft"
        assert run["why"].startswith("needs a clause that")


def test_the_report_counts_tested_and_draft_needs_standard():
    report = exchanger_kit.kit_report()
    assert report["cards"] == 17
    assert report["tested"] == 11
    assert report["draft_needs_standard"] == 6
    assert report["draft_other"] == []
    assert report["boxes"] == len(exchanger_kit.boxes()) == 49


# ---------------------------------------------- each card: passing and failing case


@pytest.mark.parametrize("card_id", HELD_IDS)
def test_each_held_card_passes_its_cases_through_the_real_code(card_id):
    run = exchanger_kit.run_kit_card(_by_id()[card_id])
    names = {r["case"] for r in run["runs"]}
    assert {"meets", "breaks", "unclear"} <= names
    assert all(r["passed"] for r in run["runs"]), run["runs"]
    assert run["status"] == "tested"


def test_the_three_limit_cards_have_an_at_the_limit_case_and_the_unit_ones_a_unit_case():
    for card_id in ("EXHD-09", "EXHD-11"):
        names = {t["name"] for t in _by_id()[card_id]["tests"]}
        assert "at the limit" in names
    # owner, 16 Nov 2026: the design pressure margin is a QUESTION until the engineer confirms the limit
    assert _by_id()["EXHD-10"]["rule"] == {
        "kind": "required",
        "field": "design_pressure",
        "right": "operating_pressure",
    }
    assert "printed in Fahrenheit" in {t["name"] for t in _by_id()["EXHD-11"]["tests"]}


def test_a_wrong_expectation_in_a_card_case_is_reported_as_a_failed_case():
    card = dict(_by_id()["EXHD-11"])
    wrong = {
        "name": "meets",
        "facts": [
            ["design temperature", "170", "C"],
            ["operating temperature", "150", "C"],
        ],
        "expect": "COMPLIANT",
    }
    card["tests"] = [wrong, *[t for t in card["tests"] if t["name"] != "meets"]]
    run = exchanger_kit.run_kit_card(card)
    assert run["status"] == "draft" and run["why"] == "a case failed"


# --------------------------------------------------------- planted exchanger defects

BASE = [
    ("design pressure", "11", "barg"),
    ("maximum operating pressure", "10", "barg"),
    ("design temperature", "190", "C"),
    ("operating temperature", "150", "C"),
    ("design code", "ASME VIII Div 1, 2023", None),
    ("minimum design metal temperature", "-29", "C"),
    ("joint efficiency", "1.0", None),
    ("corrosion allowance", "3", "mm"),
    ("tube wall thickness", "2.11", "mm"),
    ("shell material", "SA-516 70", None),
    ("tube material", "SA-179", None),
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
        "design temperature 20 C over the operating temperature",
        _sheet(design_temperature=("170", "C")),
        "EXHD-11",
        {"NON_COMPLIANT"},
    ),
    (
        "design temperature one degree under the margin",
        _sheet(design_temperature=("177", "C")),
        "EXHD-11",
        {"NON_COMPLIANT"},
    ),
    (
        "design temperature equal to the operating temperature",
        _sheet(design_temperature=("150", "C")),
        "EXHD-11",
        {"NON_COMPLIANT"},
    ),
    (
        "design temperature below the operating temperature",
        _sheet(design_temperature=("120", "C")),
        "EXHD-11",
        {"NON_COMPLIANT"},
    ),
    (
        "temperatures printed in Fahrenheit",
        _sheet(design_temperature=("350", "F"), operating_temperature=("300", "F")),
        "EXHD-11",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "design temperature in Fahrenheit against an operating temperature in Celsius",
        _sheet(design_temperature=("300", "F")),
        "EXHD-11",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "joint efficiency 0.7",
        _sheet(joint_efficiency=("0.7", None)),
        "EXHD-09",
        {"NON_COMPLIANT"},
    ),
    (
        "joint efficiency one step under the floor",
        _sheet(joint_efficiency=("0.849", None)),
        "EXHD-09",
        {"NON_COMPLIANT"},
    ),
    (
        "joint efficiency printed as a bare 70",
        _sheet(joint_efficiency=("70", None)),
        "EXHD-09",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "joint efficiency printed as 70 %",
        _sheet(joint_efficiency=("70", "%")),
        "EXHD-09",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "joint efficiency of 0 (an entry error)",
        _sheet(joint_efficiency=("0", None)),
        "EXHD-09",
        {"NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "design code missing",
        _sheet(design_code=None),
        "EXHD-01",
        {"MISSING_INFORMATION"},
    ),
    (
        "MDMT missing",
        _sheet(minimum_design_metal_temperature=None),
        "EXHD-02",
        {"MISSING_INFORMATION"},
    ),
    (
        "tube wall thickness missing",
        _sheet(tube_wall_thickness=None),
        "EXHD-03",
        {"MISSING_INFORMATION"},
    ),
    (
        "design pressure missing",
        _sheet(design_pressure=None),
        "EXHD-04",
        {"MISSING_INFORMATION"},
    ),
    (
        "operating pressure missing",
        _sheet(maximum_operating_pressure=None),
        "EXHD-05",
        {"MISSING_INFORMATION"},
    ),
    (
        "corrosion allowance missing",
        _sheet(corrosion_allowance=None),
        "EXHD-06",
        {"MISSING_INFORMATION"},
    ),
    (
        "shell material missing",
        _sheet(shell_material=None),
        "EXHD-07",
        {"MISSING_INFORMATION"},
    ),
    (
        "tube material missing",
        _sheet(tube_material=None),
        "EXHD-08",
        {"MISSING_INFORMATION"},
    ),
    (
        "joint efficiency missing",
        _sheet(joint_efficiency=None),
        "EXHD-09",
        {"MISSING_INFORMATION"},
    ),
    (
        "design pressure missing, margin rule",
        _sheet(design_pressure=None),
        "EXHD-10",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "operating temperature missing, margin rule",
        _sheet(operating_temperature=None),
        "EXHD-11",
        {"MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"},
    ),
    (
        "design code a placeholder",
        _sheet(design_code=("*", None)),
        "EXHD-01",
        {"MISSING_INFORMATION"},
    ),
    (
        "MDMT marked TBA",
        _sheet(minimum_design_metal_temperature=("TBA", None)),
        "EXHD-02",
        {"MISSING_INFORMATION"},
    ),
    (
        "tube wall thickness a placeholder",
        _sheet(tube_wall_thickness=("*", None)),
        "EXHD-03",
        {"MISSING_INFORMATION"},
    ),
]

#: Traps: inside the limit or exactly at it, each must read COMPLIANT.
TRAPS = [
    (
        "design temperature exactly 28 C over",
        _sheet(design_temperature=("178", "C")),
        "EXHD-11",
    ),
    (
        "design temperature far above",
        _sheet(design_temperature=("300", "C")),
        "EXHD-11",
    ),
    (
        "joint efficiency exactly 0.85",
        _sheet(joint_efficiency=("0.85", None)),
        "EXHD-09",
    ),
    ("joint efficiency 1.0", _sheet(), "EXHD-09"),
    ("clean sheet, design pressure stated", _sheet(), "EXHD-04"),
    ("clean sheet, tube wall thickness stated", _sheet(), "EXHD-03"),
]


@pytest.mark.parametrize(
    "what,rows,card_id,allowed", PLANTED, ids=[p[0] for p in PLANTED]
)
def test_a_planted_exchanger_defect_is_caught_never_a_pass(
    what, rows, card_id, allowed
):
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
    assert (
        len(PLANTED) >= 25
    )  # 30 before 16 Nov: the margin card's limit cases left with its numeric rule


def test_two_different_design_pressures_are_an_engineers_question_never_a_pass():
    # a shell side and a tube side design pressure printed apart: the margin card does not guess which one
    rows = [
        *_sheet(design_pressure=None),
        ("shell side design pressure", "11", "barg"),
        ("tube side design pressure", "9", "barg"),
    ]
    assert _kit_status(_by_id()["EXHD-10"], rows) in {
        "NEEDS_ENGINEER_REVIEW",
        "MISSING_INFORMATION",
    }


def test_the_clean_sheet_raises_no_fail_on_any_held_card():
    for card in exchanger_kit.cards():
        if card.get("needs"):
            continue
        # a QUESTION ONLY card (its limit an AI draft) asks on a clean sheet too: never a pass (order 14 lane D)
        want = (
            "NEEDS_ENGINEER_REVIEW"
            if question_card.question_only(card)
            else "COMPLIANT"
        )
        assert _kit_status(card, BASE) == want, card["id"]


def test_a_card_bound_is_the_cards_own_and_the_committed_role_is_untouched():
    assert "plausible" not in dc.load_rules()["roles"]["joint_efficiency"]
    # switch off: the committed checklist has no joint efficiency row and the kit's is not there either
    assert "EXHD-09" not in _live(_sheet(joint_efficiency=("70", None)))


# ------------------------------------------------- the switch and the live path


def test_the_switch_is_off_by_default_and_documented():
    from pathlib import Path

    from . import env_isolation

    assert settings.exchanger_kit_draft_enabled is False
    assert env_isolation.EGRESS_SAFE["exchanger_kit_draft_enabled"] is False
    flags = (Path(__file__).resolve().parents[2] / "docs" / "flags.md").read_text(
        encoding="utf-8"
    )
    assert "`exchanger_kit_draft_enabled` | `False`" in flags


def test_switch_off_the_exchanger_checklist_is_the_committed_one():
    committed = dc.load_rules()["checklists"][HEX]["items"]
    items = dc.checklist_for(HEX, dc.load_rules())["items"]
    assert len(items) == len(committed) == 19
    assert not [i for i in items if i["id"].startswith("EXHD")]
    assert exchanger_kit.loader_items(HEX, items) == []


def test_switch_on_only_the_cards_nothing_committed_already_asks_are_added(kit_on):
    base_ids = {i["id"] for i in dc.load_rules()["checklists"][HEX]["items"]}
    items = dc.checklist_for(HEX, dc.load_rules())["items"]
    added = [i for i in items if i["id"] not in base_ids]
    assert {i["id"] for i in added} == {
        "EXHD-01",
        "EXHD-02",
        "EXHD-09",
        "EXHD-10",
        "EXHD-11",
    }
    assert all(i["draft"] and i["kit"] == "exchanger" for i in added)
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


def test_switch_on_a_card_that_needs_a_standard_is_never_loaded_only_the_cards_a_held_clause_requires(
    kit_on,
):
    # against an empty checklist nothing is a duplicate: the eleven tested cards load, the six that need a clause do not
    ids = [i["id"] for i in exchanger_kit.loader_items(HEX, [])]
    assert ids == HELD_IDS


def test_switch_on_other_equipment_types_are_unchanged(kit_on):
    rules = dc.load_rules()
    for key in ("Pressure Safety Valve", VESSEL, "Centrifugal Pump"):
        assert exchanger_kit.loader_items(key, rules["checklists"][key]["items"]) == []
        assert not [
            i
            for i in kit_core.with_kit(key, rules["checklists"][key]["items"])
            if i["id"].startswith("EXHD")
        ]


def test_switch_off_a_low_design_pressure_margin_is_not_judged_at_all():
    assert "EXHD-10" not in _live(_sheet(design_pressure=("10.4", "barg")))
    assert "EXHD-11" not in _live(_sheet(design_temperature=("170", "C")))


def test_switch_on_low_margins_and_a_low_joint_efficiency_fail_on_a_whole_sheet(kit_on):
    out = _live(
        _sheet(
            design_pressure=("10.4", "barg"),
            design_temperature=("170", "C"),
            joint_efficiency=("0.7", None),
        )
    )
    for rule_id in ("EXHD-09", "EXHD-11"):
        assert out[rule_id]["rule_said"] == "NON_COMPLIANT", rule_id
    assert (
        "rule_said" not in out["EXHD-10"]
    )  # asked, never compared (owner, 16 Nov): no Pass kept
    for rule_id in ("EXHD-09", "EXHD-10", "EXHD-11"):
        assert out[rule_id]["draft"] is True
        assert out[rule_id]["standard"] == "SAES-E-004"
    assert out["EXHD-10"]["clause"] == "7.2.3"
    assert out["EXHD-11"]["clause"] == "7.3"
    assert out["EXHD-09"]["clause"] == "7.7"
    clean = _live(BASE)
    for rule_id in ("EXHD-09", "EXHD-11"):
        assert clean[rule_id]["rule_said"] == "COMPLIANT"
    assert "rule_said" not in clean["EXHD-10"]


def test_a_kit_card_never_decides(
    kit_on,
):  # was "even with tested cards deciding": the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)
    for card in exchanger_kit.cards():  # was card_trust.why_not / decides / DECIDING_TYPES: card_trust is retired with the switch tested_cards_decide_enabled (lead-4, 26 Nov 2026)
        held = rule_trust.check_label({"checklist": True, "draft": True, "local": False, "rule_id": card["id"]})
        assert held == rule_trust.UNPROVEN, card["id"]  # a kit card never decides: it is held for the engineer


def test_the_committed_checklists_and_their_card_report_are_untouched():
    report = rule_cards.report()
    assert report[HEX]["cards"] == 19
    assert "EXHD" not in str(report)


# ------------------------------------------- held for the engineer, always


@pytest.mark.parametrize("auto_use", [False, True])
def test_a_kit_result_is_always_held_whatever_rule_auto_use_says(
    kit_on, monkeypatch, auto_use
):  # the switch tested_cards_decide_enabled is retired with its OFF behaviour (lead-4, 26 Nov 2026)
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", auto_use)
    out = _live(
        _sheet(
            design_pressure=("10.4", "barg"),
            design_temperature=("170", "C"),
            joint_efficiency=("0.7", None),
        )
    )
    assert rule_trust.label_check(out["EXHD-10"])["status"] == "NEEDS_ENGINEER_REVIEW"
    for rule_id in ("EXHD-09", "EXHD-11"):
        row = rule_trust.label_check(out[rule_id])
        assert row["status"] == "NEEDS_ENGINEER_REVIEW", rule_id
        assert row["rule_said"] == "NON_COMPLIANT"
        assert row["detail"].startswith("The numbers read:")
    clean = _live(BASE)
    for rule_id in ("EXHD-01", "EXHD-02", "EXHD-09", "EXHD-11"):
        row = rule_trust.label_check(clean[rule_id])
        assert (
            row["status"] == "NEEDS_ENGINEER_REVIEW" and row["rule_said"] == "COMPLIANT"
        ), rule_id
    row = rule_trust.label_check(
        clean["EXHD-10"]
    )  # QUESTION ONLY: held, and no Pass kept to leave the CRS
    assert row["status"] == "NEEDS_ENGINEER_REVIEW" and not row.get("rule_said")


def test_a_signed_off_exchanger_checklist_cannot_confirm_a_kit_card(
    kit_on, monkeypatch
):
    from app import rule_trust

    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    rules = dc.load_rules()
    rules["checklists"][HEX]["sign_off"] = {"status": "signed"}
    facts = [_fact(n, v, u) for n, v, u in _sheet(design_temperature=("170", "C"))]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=HEX, page_texts=PAGES, rules=rules)
    }
    assert res["EXHD-11"]["draft"] is True and res["EXHD-11"]["local"] is True
    assert rule_trust.check_label(res["EXHD-11"]) != rule_trust.ENGINEER_CONFIRMED
    assert rule_trust.label_check(res["EXHD-11"])["status"] == "NEEDS_ENGINEER_REVIEW"
    # a committed item of the same signed checklist is confirmed as before
    assert rule_trust.check_label(res["HEX-03"]) == rule_trust.ENGINEER_CONFIRMED


def test_a_kit_row_says_it_is_an_exchanger_draft_with_unverified_clauses(kit_on):
    out = _live(_sheet(design_pressure=("10.4", "barg")))
    assert exchanger_kit.KIT_WORDS in out["EXHD-10"]["text"]
    assert "not yet verified" in out["EXHD-10"]["text"]
    assert "pump" not in out["EXHD-10"]["text"]
    assert "vessel" not in out["EXHD-10"]["text"].lower()
    assert dc.DRAFT_MARK in out["EXHD-10"]["text"]


def test_the_margin_text_states_the_factor_in_full_and_what_is_not_checked():
    one = {
        **dc.load_rules(),
        "checklists": {
            HEX: {
                "items": [_by_id()["EXHD-10"], _by_id()["EXHD-11"]],
                "sign_off": {"status": "draft"},
            }
        },
    }
    facts = [
        _fact(n, v, u)
        for n, v, u in _sheet(
            design_pressure=("10.4", "barg"), design_temperature=("170", "C")
        )
    ]
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=HEX, page_texts=PAGES, rules=one)
    }
    assert "105% of" not in res["EXHD-10"]["detail"]  # asked, never compared
    assert "28 C" in res["EXHD-11"]["detail"]
    text = _by_id()["EXHD-10"]["text"]
    assert text.startswith("AI draft, engineer to confirm") and "QUESTION ONLY" in text
    assert "1.1 x MOP" in text and "1.05 x MOP" in text and "6,900 kPa" in text
    # the stored band-2 table text is unclear: its margin is the engineer's to confirm, never stated as the clause's rule
    assert "MOP + 15 psi" in text and "MOP + 100 psi" not in text
    assert "engineer to confirm: stored table text unclear" in text
    draft = _by_id()["EXHD-10"]["limit_draft"]
    assert draft["status"] == "AI draft, engineer to confirm"
    assert draft["mop_up_to_6900_kPa"] == "greater of 1.1 x MOP and MOP + 15 psi"
    assert (
        draft["mop_6900_kPa_and_above"]
        == "greater of 1.05 x MOP and a second value that the stored text prints as 1100 psi"
    )
    assert (
        draft["mop_6900_kPa_and_above_margin"]
        == "engineer to confirm: stored table text unclear"
    )
    assert (
        "page 17" in draft["quotes_verified_against"]
        and "never the table's margins" in draft["quotes_verified_against"]
    )
    for design in (
        "10.4",
        "10",
        "9",
        "20",
    ):  # below 1.1 x MOP, equal, below MOP, far above: none is compared
        got = _kit_status(_by_id()["EXHD-10"], _sheet(design_pressure=(design, "barg")))
        assert got == "NEEDS_ENGINEER_REVIEW", (
            design
        )  # asked: never a Pass of a limit no engineer confirmed
    assert (
        "28 C" in _by_id()["EXHD-11"]["text"]
        and "Fahrenheit" in _by_id()["EXHD-11"]["text"]
    )
    assert "percentage" in _by_id()["EXHD-09"]["text"]


# ------------------------------------------- the shared mechanism, other kits unchanged


def test_the_other_kits_are_what_they_were_through_the_shared_mechanism():
    assert {k.name for k in kit_core._kits()} == {"pump", "vessel", "exchanger"}
    pump = pump_kit.kit_report()
    assert (pump["cards"], pump["tested"], pump["draft_needs_standard"]) == (19, 4, 15)
    vessel = vessel_kit.kit_report()
    assert (vessel["cards"], vessel["tested"], vessel["draft_needs_standard"]) == (
        11,
        5,
        6,
    )
    assert exchanger_kit.KIT_WORDS.startswith("DRAFT exchanger kit card")


def test_all_switches_on_each_kit_adds_only_its_own_cards(monkeypatch):
    for name in ("exchanger", "vessel", "pump"):
        monkeypatch.setattr(settings, f"{name}_kit_draft_enabled", True)
    rules = dc.load_rules()
    ids = {
        key: {i["id"] for i in dc.checklist_for(key, rules)["items"]}
        for key in (HEX, VESSEL, "Centrifugal Pump")
    }
    assert {"EXHD-09", "EXHD-11"} <= ids[HEX]
    assert not any(i.startswith(("VSLD", "PMPD")) for i in ids[HEX])
    assert {"VSLD-04", "VSLD-05"} <= ids[VESSEL]
    assert not any(i.startswith(("EXHD", "PMPD")) for i in ids[VESSEL])
    assert {"PMPD-04", "PMPD-08"} <= ids["Centrifugal Pump"]
    assert not any(i.startswith(("EXHD", "VSLD")) for i in ids["Centrifugal Pump"])


def test_a_row_is_held_with_the_words_of_its_own_kit():
    result = {"status": "COMPLIANT", "text": "t", "detail": "d"}
    rows = {
        k: kit_core.held(result, {"kit": k}) for k in ("pump", "vessel", "exchanger")
    }
    assert pump_kit.KIT_WORDS in rows["pump"]["text"]
    assert vessel_kit.KIT_WORDS in rows["vessel"]["text"]
    assert exchanger_kit.KIT_WORDS in rows["exchanger"]["text"]
    assert exchanger_kit.KIT_WORDS not in rows["vessel"]["text"]
    assert all(r["status"] == "NEEDS_ENGINEER_REVIEW" for r in rows.values())


# ------------------------------------------- review of #1849: the margin card asks for BOTH values; it quotes only the page


def test_the_margin_card_asks_for_the_mop_too():
    """It asks for the design pressure AND the MOP (the clause's limit needs both): a missing or marked MOP is said."""
    no_mop = [
        r
        for r in _sheet(design_pressure=("9", "barg"))
        if r[0] != "maximum operating pressure"
    ]
    assert _kit_status(_by_id()["EXHD-10"], no_mop) == "NEEDS_ENGINEER_REVIEW"
    rules = dc.load_rules()
    card = _by_id()["EXHD-10"]
    one = {
        **rules,
        "checklists": {HEX: {"items": [card], "sign_off": {"status": "draft"}}},
    }
    for mop, code, words in (
        (None, "other", "operating pressure the clause's limit needs is not given"),
        ("TBA", "deferred_marker", "is marked 'TBA'"),
        (
            "10",
            "limit_not_confirmed",
            "Also stated: maximum operating pressure 10 barg (page 1)",
        ),
    ):
        rows = no_mop + (
            [("maximum operating pressure", mop, "barg" if mop != "TBA" else None)]
            if mop
            else []
        )
        facts = [
            _fact(n, v, u, blank=v if v in ("*", "TBA") else None) for n, v, u in rows
        ]
        got = next(
            r
            for r in dc.evaluate(facts, equipment_type=HEX, page_texts=PAGES, rules=one)
            if r["rule_id"] == "EXHD-10"
        )
        assert (
            got["status"] == "NEEDS_ENGINEER_REVIEW"
            and got["hold_reason"] == code
            and "rule_said" not in got
        )
        assert words in got["detail"], got["detail"]


def test_the_margin_card_quotes_only_what_the_stored_page_holds():
    """Its quotes are the stored page's words (checked on page 17 by the quote check); the band-2 margin, garbled in the
    stored table text, is the engineer's to confirm and never written as the clause's rule."""
    card = _by_id()["EXHD-10"]
    draft = card["limit_draft"]
    assert (
        draft["quotes"][0]
        == "The internal design pressure shall be according to the following table"
    )
    assert all(len(q) >= 8 for q in draft["quotes"]) and "verified_against" not in draft
    assert "MOP + 100 psi" not in str(card)
