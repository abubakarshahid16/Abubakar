"""Two misses traced on the TEMA exchanger proof run e7c1ff28 (both switches on, result unchanged).

1. RULES BY EQUIPMENT SCOPE (`rules_by_equipment_scope_enabled`): a sheet named "Heat Exchanger"
   that states ASME VIII Division 1 (a pressure-vessel code) as its design code was read as
   equipment UNSURE (`subject_scope.equipment_doubt`), so the equipment set was empty and neither
   narrowing gate (`subject_scope.gate`, `equipment_scope.gate`) could leave anything out. With the
   switch on, an unsure sheet is read as EVERY type it gives (named + governed by its stated code),
   and only a rule about none of them is left out.
2. LABEL JOIN (`datasheet_label_join_enabled`): the unit check (DS-U1) read every copy of a field,
   so the unit-less twin of "0.0625 in" was still reported "needs a unit" after `_one` had already
   united the two copies (#1533 fixed one of the two homes, rule 8).

Invented labels, values and rules only (rule 13); no fixture file."""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import equipment_scope, subject_scope
from app.config import settings
from tests.test_746_relief_valve_checklist import fact

HEX = "Heat Exchanger"
CLASSIFICATION = {"equipment_type": HEX}
SHEET = [fact("design code", "ASME Section VIII Div. 1", label="Design code", page=5)]


def _req(rid, text, std="std_gen"):
    return {"id": rid, "standard_document_id": std, "requirement_text": text}


REQS = [
    _req("hx", "The heat exchanger tubes shall be seamless."),
    _req("vessel", "The pressure vessel shall be hydrostatically tested."),
    _req("general", "Bolting shall be stated."),
    _req("psv", "The relief valve shall have a lifting lever."),
]


@pytest.fixture
def scope_on(monkeypatch):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", True)


def _ids(rows):
    return sorted(r["id"] for r in rows)


def test_the_sheet_is_read_unsure_today():
    equipment, source, doubt = subject_scope.read_equipment(
        CLASSIFICATION, SHEET, subject_scope.vocabulary()
    )
    assert equipment == set() and source == subject_scope.SOURCE_UNSURE
    assert doubt["named"] == ["heat exchanger"]


def test_off_an_unsure_sheet_rules_nothing_out():
    out = subject_scope.gate(REQS, classification=CLASSIFICATION, facts=SHEET)
    assert _ids(out["kept"]) == ["general", "hx", "psv", "vessel"]


def test_on_an_unsure_sheet_leaves_out_only_a_rule_about_none_of_its_readings(scope_on):
    out = subject_scope.gate(REQS, classification=CLASSIFICATION, facts=SHEET)
    assert _ids(out["kept"]) == ["general", "hx", "vessel"]
    assert [i["requirement"]["id"] for i in out["not_applied_items"]] == ["psv"]
    assert out["summary"]["submittal_equipment"] == [
        "heat exchanger",
        "pressure vessel",
    ]
    # rule 4/7: the note no longer says "no requirement is ruled out"
    said = out["summary"]["equipment_unsure"]
    assert (
        "no requirement" not in said
        and "read as heat exchanger / pressure vessel" in said
    )


def test_on_a_sheet_not_in_doubt_is_unchanged(scope_on):
    plain = [fact("design code", "API 660", label="Design code", page=5)]
    equipment, source, doubt = equipment_scope.narrowing_equipment(
        CLASSIFICATION, plain, subject_scope.vocabulary()
    )
    assert (
        equipment == {"heat exchanger"} and doubt is None and source == "classification"
    )


def test_on_the_run_gate_leaves_out_a_scope_only_standard_of_another_type(scope_on):
    reqs = [_req("api520", "Each device shall be marked.", std="std_520"), REQS[2]]
    not_applied: list = []
    kept, result = equipment_scope.gate_for_run(
        reqs, CLASSIFICATION, SHEET, None, {"std_520": "API 520 Part I"}, not_applied
    )
    assert _ids(kept) == ["general"]
    assert [i["requirement"]["id"] for i in not_applied] == ["api520"]
    assert result["summary"]["left_out"] == 1


def test_off_the_run_gate_leaves_nothing_out():
    reqs = [_req("api520", "Each device shall be marked.", std="std_520")]
    kept, _ = equipment_scope.gate_for_run(
        reqs, CLASSIFICATION, SHEET, None, {"std_520": "API 520 Part I"}, []
    )
    assert _ids(kept) == ["api520"]


# ---------------------------------------------------------------- 2. the unit check


TWINS = [
    fact("corrosion allowance", "0.0625", page=1),
    fact("corrosion allowance", "0.0625", "in", page=5),
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
