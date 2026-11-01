"""Order 307.1: a value read for other equipment tags is never "not read" for this one. Invented values only."""

from __future__ import annotations

from app import datasheet_checks as dc
from app import read_elsewhere
from app import review as review_mod
from tests.test_746_relief_valve_checklist import PSV, fact


def _sheet(*facts):
    return [f for f in facts if f is not None]


def _by_tag(facts, rule_id):
    return {
        r["equipment_tag"]: r
        for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
        if r.get("checklist") and r["rule_id"] == rule_id
    }


TWO_VALVES = _sheet(
    fact("set pressure", "10", "barg", tag="PSV-1", page=3),
    fact("operating pressure", "8", "barg", tag="PSV-1", page=3),
    fact("operating pressure", "8", "barg", tag="PSV-2", page=4),
)


def test_the_evaluation_alone_still_calls_the_other_valves_value_missing():
    """The checks judge each tag on its own: that is why the CRS needed this pass."""
    assert _by_tag(TWO_VALVES, "PSV-01")["PSV-2"]["status"] == "MISSING_INFORMATION"


def test_a_value_read_for_one_tag_makes_the_other_tags_missing_row_an_engineer_check():
    out = read_elsewhere.soften(
        dc.evaluate(TWO_VALVES, equipment_type=PSV, page_texts={1: "x"})
    )
    row = next(
        r
        for r in out
        if r.get("checklist")
        and r["rule_id"] == "PSV-01"
        and r["equipment_tag"] == "PSV-2"
    )
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "was read on page 3" in row["detail"] and "not for PSV-2" in row["detail"]
    assert (
        "not read" not in row["detail"].lower()
        and "missing" not in row["detail"].lower()
    )
    assert row["page"] == 3  # the Page/Section cell shows where the value is


def test_the_tag_that_has_the_value_is_untouched():
    out = read_elsewhere.soften(
        dc.evaluate(TWO_VALVES, equipment_type=PSV, page_texts={1: "x"})
    )
    mine = next(
        r
        for r in out
        if r.get("checklist")
        and r["rule_id"] == "PSV-01"
        and r["equipment_tag"] == "PSV-1"
    )
    assert mine["status"] == "COMPLIANT"


def test_a_value_missing_on_every_tag_stays_missing():
    sheet = _sheet(
        fact("operating pressure", "8", "barg", tag="PSV-1"),
        fact("operating pressure", "8", "barg", tag="PSV-2"),
    )
    out = read_elsewhere.soften(
        dc.evaluate(sheet, equipment_type=PSV, page_texts={1: "x"})
    )
    rows = [r for r in out if r.get("checklist") and r["rule_id"] == "PSV-01"]
    assert rows and {r["status"] for r in rows} == {"MISSING_INFORMATION"}


def test_a_placeholder_on_the_other_tag_is_not_a_value_that_was_read():
    sheet = _sheet(
        fact("set pressure", "*", blank="*", tag="PSV-1"),
        fact("operating pressure", "8", "barg", tag="PSV-1"),
        fact("operating pressure", "8", "barg", tag="PSV-2"),
    )
    out = read_elsewhere.soften(
        dc.evaluate(sheet, equipment_type=PSV, page_texts={1: "x"})
    )
    rows = {
        r["equipment_tag"]: r
        for r in out
        if r.get("checklist") and r["rule_id"] == "PSV-01"
    }
    assert rows["PSV-1"]["status"] == "MISSING_INFORMATION"
    assert rows["PSV-2"]["status"] == "MISSING_INFORMATION"


def test_the_stored_finding_says_a_value_was_read_never_not_read(monkeypatch):
    written = []
    monkeypatch.setattr(review_mod, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(
        review_mod,
        "create",
        lambda row, created_by=None: written.append(row) or {"id": "x", **row},
    )
    out = [
        r
        for r in dc.evaluate(TWO_VALVES, equipment_type=PSV, page_texts={1: "x"})
        if r.get("checklist") and r["rule_id"] == "PSV-01"
    ]
    dc.store("run", "sub", out, pages_read={1: "read"})
    row = next(w for w in written if w["equipment_tag"] == "PSV-2")
    assert row["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert row["contractor_page"] == 3
    assert "was read on page 3" in row["finding"]
    assert "Contractor to provide" not in row["required_action"]


def test_only_a_missing_row_is_softened_a_reader_gap_row_keeps_its_own_words():
    def row(tag, status, fact_id, detail):
        return {
            "rule_id": "X-1",
            "status": status,
            "checklist": True,
            "role": "set_pressure",
            "field": "Set pressure",
            "equipment_tag": tag,
            "fact_id": fact_id,
            "page": 3 if fact_id else None,
            "detail": detail,
        }

    gap = row(
        "B",
        "NEEDS_ENGINEER_REVIEW",
        None,
        "wording for it appears on page 2: engineer to check.",
    )
    out = read_elsewhere.soften([row("A", "COMPLIANT", "f1", "stated"), gap])
    assert out[1] == gap


def test_a_missing_result_that_is_not_a_checklist_item_is_left_alone():
    """The mandatory-field check (DS-M1) has its own wording and is not part of this pass."""
    read = {
        "rule_id": "X-1",
        "status": "COMPLIANT",
        "checklist": True,
        "role": "set_pressure",
        "field": "Set pressure",
        "equipment_tag": "A",
        "fact_id": "f1",
        "page": 3,
        "detail": "stated",
    }
    mandatory = {
        "rule_id": "DS-M1",
        "status": "MISSING_INFORMATION",
        "role": "set_pressure",
        "field": "Set pressure",
        "equipment_tag": "B",
        "fact_id": None,
        "page": None,
        "detail": "not found in the fields read from the datasheet.",
    }
    assert read_elsewhere.soften([read, mandatory])[1] == mandatory
