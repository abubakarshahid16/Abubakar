"""Two misses traced on an exchanger proof run (both switches on, result unchanged).

1. RULES BY EQUIPMENT SCOPE (`rules_by_equipment_scope_enabled`): a sheet named "Heat Exchanger"
   that states ASME VIII Division 1 (a pressure-vessel code) as its design code is read as
   equipment UNSURE (`subject_scope.equipment_doubt`, order 142), so no gate could act. An unsure
   sheet still rules nothing out: a rule about none of its possible types is HELD for the engineer,
   counted on its own line ("applies only if this is a ..."), never `other_equipment`.
2. LABEL JOIN (`datasheet_label_join_enabled`): the unit check (DS-U1) read every copy of a field,
   so the unit-less twin of "0.0472 in" was still reported "needs a unit" after `_one` had already
   united the two copies (#1533 fixed one of the two homes, rule 8).

Invented labels, values and rules only (rule 13); no fixture file."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import equipment_scope, held_findings, scope_ledger, subject_scope
from app.config import settings
from tests.test_746_relief_valve_checklist import fact
from tests.test_partial_standards import temp_storage as review_storage  # noqa: F401
from tests.test_rules_by_equipment_scope import _review

HEX = "Heat Exchanger"
ASME_VIII = "ASME Section VIII Div. 1"
SHEET = [fact("design code", ASME_VIII, label="Design code", page=5)]
LABELS = {"std_660": "API 660", "std_520": "API 520 Part I", "std_gen": "ACME Practice"}


def _req(rid, text, std="std_gen"):
    return {"id": rid, "standard_document_id": std, "requirement_text": text}


@pytest.fixture
def scope_on(monkeypatch):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", True)


def _ids(rows):
    return sorted(r["id"] for r in rows)


def _run_gate(reqs, equipment_type=HEX, facts=SHEET):
    not_applied: list = []
    kept, result = equipment_scope.gate_for_run(
        reqs, {"equipment_type": equipment_type}, facts, None, LABELS, not_applied
    )
    return kept, result, not_applied


def test_the_sheet_is_read_unsure():
    equipment, source, doubt = subject_scope.read_equipment(
        {"equipment_type": HEX}, SHEET, subject_scope.vocabulary()
    )
    assert equipment == set() and source == subject_scope.SOURCE_UNSURE
    assert doubt["named"] == ["heat exchanger"]


def test_an_unconfirmed_pump_stating_asme_viii_never_loses_an_exchanger_rule(
    review_storage, scope_on
):
    """The reviewer's case: the sheet may really be an exchanger. Its rules are held, not lost."""
    reqs = [
        _req("hx", "The heat exchanger tubes shall be seamless."),
        _req("api660", "Each item shall be marked.", std="std_660"),
        _req("pump", "The pump casing shall be stated."),
        _req("vessel", "The pressure vessel shall be tested."),
        _req("general", "Bolting shall be stated."),
    ]
    kept, result, not_applied = _run_gate(reqs, equipment_type="Pump")
    assert not_applied == []  # nothing is other_equipment on an unsure reading
    assert _ids(kept) == ["general", "pump", "vessel"]
    assert _ids(i["requirement"] for i in result["held"]) == ["api660", "hx"]
    assert {i["code"] for i in result["held"]} == {"equipment_unconfirmed"}
    for item in result["held"]:
        assert item["detail"] == (
            "applies only if this is a heat exchanger: engineer to confirm"
        )


def test_the_held_group_is_counted_on_its_own_line_and_names_the_doubt(
    review_storage, scope_on
):
    reqs = [
        _req("psv", "The relief valve shall have a lever."),
        _req("general", "Bolting shall be stated."),
    ]
    _kept, result, _ = _run_gate(reqs)
    summary = result["summary"]
    # the guess is never the submittal's equipment (rule 4)
    assert summary["submittal_equipment"] == []
    assert summary["left_out"] == 0
    held = summary["held_equipment_unconfirmed"]
    assert held["count"] == 1
    assert held["possible_types"] == ["heat exchanger", "pressure vessel"]
    lines = equipment_scope.lines(
        {"requirement_split": equipment_scope.split_part(result)}
    )
    (line,) = [x["line"] for x in lines]
    assert line.startswith("1 rules held for the engineer: 1 apply only if this is a")
    assert "equipment type is unsure" in line
    assert "a guess: heat exchanger / pressure vessel" in line
    assert "of the 2 rules of the standards in scope" in line
    assert "this submittal is" not in line


def test_a_rule_a_possible_type_could_take_stays_in(review_storage, scope_on):
    reqs = [
        _req("hx", "The heat exchanger tubes shall be seamless."),
        _req("vessel", "The pressure vessel shall be tested."),
    ]
    kept, result, _ = _run_gate(reqs)
    assert _ids(kept) == ["hx", "vessel"] and result["held"] == []
    assert "held_equipment_unconfirmed" not in result["summary"]


def test_a_scope_only_standard_of_another_type_is_held_too(review_storage, scope_on):
    reqs = [_req("api520", "Each device shall be marked.", std="std_520")]
    kept, result, not_applied = _run_gate(reqs)
    assert kept == [] and not_applied == []
    assert result["held"][0]["detail"] == (
        "applies only if this is a relief valve: engineer to confirm"
    )


def test_a_confirmed_type_is_not_in_doubt_and_still_leaves_a_rule_out(
    review_storage, scope_on
):
    reqs = [_req("api520", "Each device shall be marked.", std="std_520")]
    not_applied: list = []
    kept, result = equipment_scope.gate_for_run(
        reqs,
        {"equipment_type": HEX, "confirmed_by": "engineer"},
        SHEET,
        None,
        LABELS,
        not_applied,
    )
    assert kept == [] and result["held"] == []
    assert [i["code"] for i in not_applied] == ["other_equipment_scope"]


def test_off_nothing_is_held(review_storage):
    reqs = [_req("psv", "The relief valve shall have a lever.")]
    kept, result, not_applied = _run_gate(reqs)
    assert _ids(kept) == ["psv"] and not_applied == []
    assert result["held"] == [] and result["summary"] is None


def test_order_142_the_unsure_note_stays_true_with_the_switch_on(scope_on):
    """applicability.py and `subject_scope.gate` print this reason: a held rule is not ruled out."""
    out = subject_scope.gate(
        [_req("psv", "The relief valve shall have a lever.")],
        classification={"equipment_type": HEX},
        facts=SHEET,
    )
    assert _ids(out["kept"]) == ["psv"] and out["not_applied"] == []
    assert out["summary"]["submittal_equipment"] == []
    assert "no requirement is ruled out" in out["summary"]["equipment_unsure"]


def test_the_held_kind_has_its_own_words_on_a_grouped_row():
    item = {"code": equipment_scope.HELD_CODE}
    assert held_findings.kind_of(item) == "equipment_unconfirmed"
    assert "engineer to confirm" in held_findings.KINDS["equipment_unconfirmed"]


def test_review_holds_the_rule_applies_not_checked_with_an_engineer_row(
    review_storage, scope_on
):
    result, stored, rid = _review(HEX, "API-610.pdf", design_code=ASME_VIII)
    assert stored[rid]["reason_code"] == "equipment_unconfirmed"
    assert stored[rid]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    note = result["requirement_split"]["equipment_scope"]
    assert note["left_out"] == 0
    assert note["held_equipment_unconfirmed"]["count"] == 1
    assert result["requirement_split"]["applies_not_checked"] == 1


def test_review_with_the_switch_off_compares_the_rule_as_before(
    review_storage, monkeypatch
):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", False)
    result, stored, rid = _review(HEX, "API-610.pdf", design_code=ASME_VIII)
    assert stored[rid]["reason_code"] != "equipment_unconfirmed"
    assert "equipment_scope" not in result["requirement_split"]


# ---------------------------------------------------------------- 2. the unit check


TWINS = [
    fact("corrosion allowance", "0.0472", page=1),
    fact("corrosion allowance", "0.0472", "in", page=5),
]


def _unit_rows(facts):
    rows = dc.evaluate(facts, equipment_type=HEX, page_texts={1: "x"})
    return [
        r
        for r in rows
        if r.get("rule_id") == "DS-U1" and r.get("role") == "corrosion_allowance"
    ]


def test_off_the_unit_less_twin_still_needs_a_unit():
    assert len(_unit_rows(TWINS)) == 1


def test_on_the_unit_less_twin_of_a_united_reading_needs_no_unit(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_label_join_enabled", True)
    assert _unit_rows(TWINS) == []


def test_on_a_unit_less_reading_alone_still_needs_a_unit(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_label_join_enabled", True)
    assert len(_unit_rows([TWINS[0]])) == 1


def test_on_a_unit_less_reading_of_another_number_still_needs_a_unit(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_label_join_enabled", True)
    other = [fact("corrosion allowance", "0.125", page=1), TWINS[1]]
    assert len(_unit_rows(other)) == 1
