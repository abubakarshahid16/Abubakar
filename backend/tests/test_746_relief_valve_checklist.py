"""#746: the review checklist per equipment type, in the one datasheet-checks
engine. The relief valve checklist first, DRAFT until a client engineer signs
it off. Every item carries its clause; code decides each one (compliant,
non-compliant, missing, needs an engineer with the reason, or does not apply
with the reason). Invented values only.
"""
from __future__ import annotations

import json

import pytest

from app import datasheet_checks as dc

PSV = "Pressure Safety Valve"


def fact(name, value, unit=None, *, label=None, page=2, blank=None, note=None, tag=None):
    return {"id": f"f-{name}-{value}-{tag}", "field_name": name, "field_label": label or name.capitalize(),
            "field_value": f"{value} {unit}".strip() if unit else value,
            "raw_value": None if blank else value, "raw_unit": unit,
            "normalized_value": None, "normalized_unit": None,
            "is_blank": 1 if blank else 0, "blank_marker": blank, "value_note": note,
            "page": page, "equipment_tag": tag}


def results(facts):
    return {r["rule_id"]: r for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
            if r.get("checklist")}


SHEET = [
    fact("set pressure", "10", "barg", note="By Contractor"),
    fact("max allow working pressure", "12", "barg"),
    fact("design pressure", "12", "barg"),
    fact("operating pressure", "8.5", "barg"),
    fact("over pressure", "21", label="Over pressure %"),
    fact("back press variable", "0.8", "barg"),
    fact("relief case", "Fire"),
    fact("valve type", "Conventional"),
    fact("fluid phase", "Gas"),
    fact("specific heat ratio cp/cv", "1.3"),
]


def test_the_relief_valve_checklist_is_a_draft_and_every_item_cites_a_clause():
    checklist = dc.checklist_for(PSV, dc.load_rules())
    assert checklist["draft"] is True
    assert len(checklist["items"]) >= 30
    for item in checklist["items"]:
        assert item["source"]["standard"] and item["source"]["clause"]
    assert dc.checklist_for("Pressure Vessel", dc.load_rules()) is None   # not drafted yet


def test_each_rule_kind_is_decided_by_code():
    r = results(SHEET)
    assert r["PSV-01"]["status"] == "COMPLIANT"                    # set pressure stated
    assert "By Contractor" in r["PSV-01"]["detail"]                # the note is named
    assert r["PSV-24"]["status"] == "COMPLIANT"                    # 10 barg <= MAWP 12 barg
    assert r["PSV-25"]["status"] == "COMPLIANT"                    # MAWP 12 >= design 12
    assert r["PSV-26"]["status"] == "COMPLIANT"                    # 8.5 <= 90% of 10
    assert r["PSV-29"]["status"] == "COMPLIANT"                    # 0.8 <= 10% of 10 (conventional)
    assert r["PSV-16"]["status"] == "COMPLIANT"                    # allowed valve type
    assert r["PSV-32"]["status"] == "COMPLIANT"                    # k > 1 for a gas
    assert r["PSV-12"]["status"] == "MISSING_INFORMATION"          # orifice area not given


def test_a_breach_is_non_compliant_with_both_values_and_the_clause():
    over = [f for f in SHEET if f["field_name"] != "max allow working pressure"] + [
        fact("max allow working pressure", "9.5", "barg")]
    r = results(over)["PSV-24"]
    assert r["status"] == "NON_COMPLIANT"
    assert "10 barg" in r["detail"] and "9.5 barg" in r["detail"]
    assert "API 520-I 5.4.2.1" in r["text"] and "DRAFT" in r["text"]
    assert r["severity"] == "critical"
    tight = [f for f in SHEET if f["field_name"] != "operating pressure"] + [
        fact("operating pressure", "9.5", "barg")]
    assert results(tight)["PSV-26"]["status"] == "NON_COMPLIANT"   # 9.5 > 90% of 10


def test_a_condition_decides_whether_an_item_applies():
    r = results(SHEET)
    assert r["PSV-27"]["status"] == "COMPLIANT"                    # fire case: 21% <= 21% (unit from the label)
    assert r["PSV-28"]["status"] == "NOT_APPLICABLE"               # the non-fire 10% limit does not apply
    assert "Fire" in r["PSV-28"]["detail"]
    assert r["PSV-22"]["status"] == "NOT_APPLICABLE"               # liquid-only item on a gas
    no_case = [f for f in SHEET if f["field_name"] != "relief case"]
    r = results(no_case)
    assert r["PSV-27"]["status"] == "NEEDS_ENGINEER_REVIEW"        # case unknown: never guessed
    assert "relief case" in r["PSV-27"]["detail"].lower()


def test_a_blank_field_is_missing_with_its_page_and_values_on_two_scales_are_not_guessed():
    blank = [f for f in SHEET if f["field_name"] != "set pressure"] + [
        fact("set pressure", "", blank="By Contractor", page=3)]
    r = results(blank)
    assert r["PSV-01"]["status"] == "MISSING_INFORMATION" and "page 3" in r["PSV-01"]["detail"]
    mixed = [f for f in SHEET if f["field_name"] != "max allow working pressure"] + [
        fact("max allow working pressure", "12", "bara")]
    assert results(mixed)["PSV-24"]["status"] == "NEEDS_ENGINEER_REVIEW"   # gauge against absolute


def test_an_item_without_a_clause_is_refused():
    rules = dc.load_rules()
    rules["checklists"][PSV]["items"].append({"id": "X", "text": "t", "source": {"standard": "S"},
                                              "rule": {"kind": "required", "field": "fluid"}})
    with pytest.raises(ValueError, match="source clause"):
        dc.checklist_for(PSV, rules)


def test_local_items_are_merged_and_marked_local(tmp_path, monkeypatch):
    """Items drawn from a client's own standard live in the git-ignored data
    folder (CLAUDE.md rule 1) and run beside the committed ones."""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "pressure_safety_valve.json").write_text(json.dumps({"items": [
        {"id": "LOC-01", "text": "The fluid is stated.", "source": {"standard": "Company std", "clause": "1.1"},
         "rule": {"kind": "required", "field": "fluid"}}]}), encoding="utf-8")
    checklist = dc.checklist_for(PSV, dc.load_rules())
    local = [i for i in checklist["items"] if i.get("local")]
    assert [i["id"] for i in local] == ["LOC-01"]
    assert results(SHEET)["LOC-01"]["status"] == "MISSING_INFORMATION"


def test_does_not_apply_is_never_written_as_a_finding(monkeypatch):
    written = []
    from app import review as review_mod
    monkeypatch.setattr(review_mod, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(review_mod, "create", lambda row, created_by=None: written.append(row) or {"id": "x"})

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): return self

    import app.db as db_mod
    monkeypatch.setattr(db_mod, "connect", lambda: _Conn())
    only = [r for r in dc.evaluate(SHEET, equipment_type=PSV, page_texts={})
            if r.get("checklist") and r["status"] in ("NOT_APPLICABLE", "COMPLIANT")]
    assert only
    dc.store("run", "sub", only, pages_read={})
    assert written == []


def test_an_unknown_condition_stops_only_the_items_it_could_make_wrong():
    """No fluid phase on the sheet: "the molecular weight is stated" is still
    decided (it cannot be wrong whatever the phase); a limit that depends on
    the relief case is not."""
    no_phase = [f for f in SHEET if f["field_name"] != "fluid phase"] + [
        fact("mole wt of relieved fluid", "28")]
    r = results(no_phase)
    assert r["PSV-19"]["status"] == "COMPLIANT"                    # MW stated, phase unknown
    assert r["PSV-32"]["status"] == "COMPLIANT"                    # k > 1, phase unknown
    assert r["PSV-22"]["status"] == "NEEDS_ENGINEER_REVIEW"        # liquid density not given, phase unknown:
    assert "fluid phase" in r["PSV-22"]["detail"].lower()          # not owed for sure, so not "missing"
    no_case = [f for f in SHEET if f["field_name"] != "relief case"]
    assert results(no_case)["PSV-28"]["status"] == "NEEDS_ENGINEER_REVIEW"
